from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit

import requests


DELIVERY_PROTOCOL = "groupguard-query-delivery.v1"
_QUERY_PATH = "/api/v1/groupguard/query"
_REPORT_PATH = "/api/v1/groupguard/report"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_ALLOWED_PREFERRED = {"auto", "text", "image", "forward"}
_ALLOWED_REPORT_FEATURES = {"scammer_report", "peer_report"}


class QueryClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, retry_after_seconds: int = 0):
        super().__init__(message)
        self.code = str(code or "query_client_error")
        self.user_message = str(message or "查询失败")
        self.retryable = bool(retryable)
        self.retry_after_seconds = max(0, int(retry_after_seconds or 0))


@dataclass(frozen=True)
class DeliverySegment:
    type: str
    text: str = ""
    mime_type: str = ""
    filename: str = ""
    data: bytes = b""
    nodes: tuple[tuple["DeliverySegment", ...], ...] = ()


@dataclass(frozen=True)
class DeliveryEnvelope:
    feature: str
    request_id: str
    client_request_id: str
    segments: tuple[DeliverySegment, ...]
    meta: Dict[str, Any]

    def text(self) -> str:
        chunks: List[str] = []
        for segment in self.segments:
            if segment.type == "text" and segment.text:
                chunks.append(segment.text)
            elif segment.type == "forward":
                for node in segment.nodes:
                    node_text = "\n".join(item.text for item in node if item.type == "text" and item.text)
                    if node_text:
                        chunks.append(node_text)
        return "\n\n".join(chunks).strip()

    def images(self) -> tuple[DeliverySegment, ...]:
        return tuple(segment for segment in self.segments if segment.type == "image")


def _safe_request_id(value: str = "") -> str:
    raw = str(value or uuid.uuid4().hex).strip()
    cleaned = _SAFE_ID_RE.sub("-", raw).strip("-")[:128]
    return cleaned or uuid.uuid4().hex


def _is_intranet_host(hostname: str) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain", "::1"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Single-label hostnames are commonly provided by LAN DNS. Fully
        # qualified public hostnames are deliberately rejected by this client.
        return "." not in host
    return bool(address.is_private or address.is_loopback)


def normalize_intranet_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise QueryClientError("invalid_base_url", "内网接口地址无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise QueryClientError("invalid_base_url", "内网接口地址必须是完整的 http/https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise QueryClientError("invalid_base_url", "内网接口地址不能包含凭据、查询参数或片段")
    if parsed.path not in {"", "/"}:
        raise QueryClientError("invalid_base_url", "内网接口地址不能包含业务路径")
    if not _is_intranet_host(parsed.hostname):
        raise QueryClientError("public_base_url_forbidden", "查询客户端只允许连接内网接口")
    return f"{parsed.scheme}://{parsed.netloc}"


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise QueryClientError("invalid_delivery", "接口返回字段过长")
    return text


def _parse_text_segment(value: Mapping[str, Any]) -> DeliverySegment:
    text = _bounded_text(value.get("text"), 20000)
    return DeliverySegment(type="text", text=text)


def _parse_image_segment(value: Mapping[str, Any]) -> DeliverySegment:
    if str(value.get("encoding") or "") != "base64":
        raise QueryClientError("invalid_delivery", "图片交付编码不受支持")
    encoded = str(value.get("data") or "")
    if len(encoded) > 16 * 1024 * 1024:
        raise QueryClientError("invalid_delivery", "图片交付数据过大")
    try:
        body = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise QueryClientError("invalid_delivery", "图片交付数据不是有效 Base64") from exc
    declared_bytes = int(value.get("bytes") or len(body))
    if declared_bytes != len(body) or len(body) > 12 * 1024 * 1024:
        raise QueryClientError("invalid_delivery", "图片交付字节数不一致或超过限制")
    declared_sha = str(value.get("sha256") or "").lower()
    actual_sha = hashlib.sha256(body).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", declared_sha) or declared_sha != actual_sha:
        raise QueryClientError("invalid_delivery", "图片交付哈希校验失败")
    mime_type = _bounded_text(value.get("mime_type"), 128).lower()
    if not mime_type.startswith("image/"):
        raise QueryClientError("invalid_delivery", "图片交付 MIME 类型无效")
    filename = _bounded_text(value.get("filename"), 128) or "query-image"
    return DeliverySegment(
        type="image",
        mime_type=mime_type,
        filename=filename,
        data=body,
    )


def _parse_segments(values: Any, *, depth: int = 0) -> tuple[DeliverySegment, ...]:
    if depth > 2 or not isinstance(values, list) or len(values) > 64:
        raise QueryClientError("invalid_delivery", "接口返回的消息段结构无效")
    result: List[DeliverySegment] = []
    for item in values:
        if not isinstance(item, Mapping):
            raise QueryClientError("invalid_delivery", "接口返回包含无效消息段")
        segment_type = str(item.get("type") or "").strip()
        if segment_type == "text":
            result.append(_parse_text_segment(item))
        elif segment_type == "image":
            result.append(_parse_image_segment(item))
        elif segment_type == "forward":
            raw_nodes = item.get("nodes")
            if not isinstance(raw_nodes, list) or not raw_nodes or len(raw_nodes) > 32:
                raise QueryClientError("invalid_delivery", "合并转发节点结构无效")
            nodes: List[tuple[DeliverySegment, ...]] = []
            for node in raw_nodes:
                if not isinstance(node, Mapping):
                    raise QueryClientError("invalid_delivery", "合并转发节点无效")
                nodes.append(_parse_segments(node.get("segments"), depth=depth + 1))
            result.append(DeliverySegment(type="forward", nodes=tuple(nodes)))
        else:
            raise QueryClientError("invalid_delivery", f"接口返回不支持的消息段：{segment_type or 'unknown'}")
    if not result:
        raise QueryClientError("invalid_delivery", "接口没有返回可发送内容")
    return tuple(result)


def parse_delivery_envelope(value: Any, *, expected_feature: str) -> DeliveryEnvelope:
    if not isinstance(value, Mapping):
        raise QueryClientError("invalid_envelope", "接口返回不是对象")
    if value.get("protocol") != DELIVERY_PROTOCOL:
        raise QueryClientError("protocol_mismatch", "接口协议版本不匹配")
    feature = _bounded_text(value.get("feature"), 96)
    if feature != expected_feature:
        raise QueryClientError("feature_mismatch", "接口返回了错误的功能类型")
    retry = value.get("retry") if isinstance(value.get("retry"), Mapping) else {}
    if value.get("ok") is not True:
        error = value.get("error") if isinstance(value.get("error"), Mapping) else {}
        raise QueryClientError(
            _bounded_text(error.get("code"), 96) or "request_failed",
            _bounded_text(error.get("user_message"), 500) or "查询失败，请稍后再试",
            retryable=bool(error.get("retryable") or retry.get("allowed")),
            retry_after_seconds=int(retry.get("after_seconds") or 0),
        )
    delivery = value.get("delivery") if isinstance(value.get("delivery"), Mapping) else {}
    kind = str(delivery.get("kind") or "")
    raw_segments = delivery.get("segments")
    if kind not in {"segments", "forward"}:
        raise QueryClientError("invalid_delivery", "接口交付类型无效")
    segments = _parse_segments(raw_segments)
    request_id = _bounded_text(value.get("request_id"), 128)
    client_request_id = _bounded_text(value.get("client_request_id"), 128)
    meta = dict(value.get("meta")) if isinstance(value.get("meta"), Mapping) else {}
    return DeliveryEnvelope(
        feature=feature,
        request_id=request_id,
        client_request_id=client_request_id,
        segments=segments,
        meta=meta,
    )


class IntranetQueryClient:
    """Reference client for SnowLuma, official bots, and future channels.

    This class deliberately contains no provider URL, credential, HTML/JSON
    business parser, renderer, cache, fallback source, or platform-specific
    message object. A channel adapter only converts the validated segments into
    its own SDK calls.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        session: Optional[requests.Session] = None,
        client_name: str = "channel-neutral-client",
    ) -> None:
        self.base_url = normalize_intranet_base_url(base_url)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
        self.session = session or requests.Session()
        self.client_name = str(client_name or "channel-neutral-client")[:64]

    def _post(self, path: str, payload: Mapping[str, Any], expected_feature: str) -> DeliveryEnvelope:
        response: Optional[requests.Response] = None
        try:
            response = self.session.post(
                f"{self.base_url}{path}",
                json=dict(payload),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=(min(3.0, self.timeout_seconds), self.timeout_seconds),
            )
            if len(response.content) > 16 * 1024 * 1024:
                raise QueryClientError("response_too_large", "接口响应超过客户端限制")
            try:
                decoded = response.json()
            except ValueError as exc:
                raise QueryClientError("invalid_json", f"接口返回非 JSON（HTTP {response.status_code}）") from exc
            envelope = parse_delivery_envelope(decoded, expected_feature=expected_feature)
            if not response.ok:
                raise QueryClientError("http_status_conflict", f"接口 HTTP 状态异常：{response.status_code}")
            return envelope
        except QueryClientError:
            raise
        except requests.Timeout as exc:
            raise QueryClientError("request_timeout", "内网查询请求超时", retryable=True) from exc
        except requests.RequestException as exc:
            raise QueryClientError("request_failed", "无法连接内网查询服务", retryable=True) from exc
        finally:
            if response is not None:
                response.close()

    def query(
        self,
        feature: str,
        parameters: Mapping[str, Any],
        *,
        preferred: str = "auto",
        capabilities: Optional[Mapping[str, bool]] = None,
        request_id: str = "",
    ) -> DeliveryEnvelope:
        normalized_feature = _bounded_text(feature, 96)
        if not normalized_feature:
            raise QueryClientError("feature_required", "查询功能不能为空")
        normalized_preferred = preferred if preferred in _ALLOWED_PREFERRED else "auto"
        clean_parameters = {
            str(key).strip(): str(value).strip()
            for key, value in dict(parameters or {}).items()
            if str(key).strip() and str(value).strip()
        }
        if not clean_parameters:
            raise QueryClientError("parameters_required", "查询参数不能为空")
        payload = {
            "feature": normalized_feature,
            "parameters": clean_parameters,
            "preferred": normalized_preferred,
            "capabilities": {
                "text": bool((capabilities or {}).get("text", True)),
                "image": bool((capabilities or {}).get("image", True)),
                "forward": bool((capabilities or {}).get("forward", True)),
            },
            "request_id": _safe_request_id(request_id),
            "client": self.client_name,
        }
        return self._post(_QUERY_PATH, payload, normalized_feature)

    def report(
        self,
        feature: str,
        parameters: Mapping[str, Any],
        *,
        request_id: str,
        preferred: str = "text",
    ) -> DeliveryEnvelope:
        normalized_feature = _bounded_text(feature, 96)
        if normalized_feature not in _ALLOWED_REPORT_FEATURES:
            raise QueryClientError("report_feature_invalid", "举报功能类型无效")
        clean_parameters = {
            str(key).strip(): str(value).strip()
            for key, value in dict(parameters or {}).items()
            if str(key).strip() and str(value).strip()
        }
        if not clean_parameters:
            raise QueryClientError("parameters_required", "举报参数不能为空")
        payload = {
            "feature": normalized_feature,
            "parameters": clean_parameters,
            "preferred": preferred if preferred in {"text", "forward"} else "text",
            "capabilities": {"text": True, "image": False, "forward": True},
            "request_id": _safe_request_id(request_id),
            "client": self.client_name,
        }
        return self._post(_REPORT_PATH, payload, normalized_feature)
