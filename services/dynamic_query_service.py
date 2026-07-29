from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import requests
from fastapi import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config" / "dynamic-query-providers.default.json"
LOCAL_CATALOG_PATH = PROJECT_ROOT / "config" / "dynamic-query-providers.json"
CATALOG_SCHEMA = "lolapi-dynamic-query-providers.v1"
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_PARAMETER_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_TOKEN_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_PATH_TOKEN_RE = re.compile(r"([^.[\]]+)|\[(\d+)\]")
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class DynamicProviderDefinition:
    command_id: str
    method: str
    url: str
    headers: Dict[str, str]
    query: Dict[str, str]
    body: Dict[str, str]
    timeout_ms: int
    text_path: str
    fallback_text: str
    snapshot_seconds: int
    allow_private: bool


class DynamicProviderCatalog:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._path = Path()
        self._mtime_ns = -1
        self._definitions: Dict[str, DynamicProviderDefinition] = {}

    @staticmethod
    def configured_path() -> Path:
        configured = str(os.getenv("DYNAMIC_QUERY_PROVIDERS_PATH") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        if LOCAL_CATALOG_PATH.is_file():
            return LOCAL_CATALOG_PATH.resolve()
        return DEFAULT_CATALOG_PATH.resolve()

    @staticmethod
    def _string_map(value: Any, label: str) -> Dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} 必须是对象")
        result: Dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip()
            item = str(raw_value or "").strip()
            if not key or not item:
                continue
            if len(key) > 128 or len(item) > 4096:
                raise ValueError(f"{label} 字段过长")
            result[key] = item
        return result

    @classmethod
    def _definition(cls, value: Any) -> DynamicProviderDefinition:
        if not isinstance(value, Mapping):
            raise ValueError("动态 Provider 定义必须是对象")
        command_id = str(value.get("id") or "").strip()
        if not _COMMAND_ID_RE.fullmatch(command_id):
            raise ValueError("动态命令 id 无效")
        provider = value.get("provider") if isinstance(value.get("provider"), Mapping) else {}
        response = value.get("response") if isinstance(value.get("response"), Mapping) else {}
        method = str(provider.get("method") or "GET").strip().upper()
        if method not in {"GET", "POST"}:
            raise ValueError(f"动态命令 {command_id} 仅支持 GET/POST")
        url = str(provider.get("url") or "").strip()
        parts = urlsplit(url.replace("$sample", "sample"))
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"动态命令 {command_id} Provider URL 无效")
        timeout_ms = max(1000, min(int(provider.get("timeout_ms") or provider.get("timeoutMs") or 5000), 15000))
        snapshot_seconds = max(0, min(int(value.get("snapshot_seconds") or 3600), 604800))
        text_path = str(response.get("text_path") or response.get("textPath") or "").strip()
        if len(text_path) > 256:
            raise ValueError(f"动态命令 {command_id} 响应路径过长")
        return DynamicProviderDefinition(
            command_id=command_id,
            method=method,
            url=url,
            headers=cls._string_map(provider.get("headers"), "headers"),
            query=cls._string_map(provider.get("query"), "query"),
            body=cls._string_map(provider.get("body"), "body"),
            timeout_ms=timeout_ms,
            text_path=text_path,
            fallback_text=str(value.get("fallback_text") or "动态查询暂时不可用，请稍后再试")[:500],
            snapshot_seconds=snapshot_seconds,
            allow_private=bool(provider.get("allow_private")),
        )

    @classmethod
    def _load_path(cls, path: Path) -> Dict[str, DynamicProviderDefinition]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema") != CATALOG_SCHEMA:
            raise ValueError("动态 Provider 目录 schema 不受支持")
        commands = raw.get("commands")
        if not isinstance(commands, list):
            raise ValueError("动态 Provider 目录缺少 commands 数组")
        definitions: Dict[str, DynamicProviderDefinition] = {}
        for item in commands:
            definition = cls._definition(item)
            if definition.command_id in definitions:
                raise ValueError(f"动态命令 id 重复：{definition.command_id}")
            definitions[definition.command_id] = definition
        return definitions

    def get(self, command_id: str) -> DynamicProviderDefinition:
        path = self.configured_path()
        try:
            stat = path.stat()
        except OSError as exc:
            raise HTTPException(status_code=503, detail="动态查询 Provider 目录不存在") from exc
        with self._lock:
            if path != self._path or stat.st_mtime_ns != self._mtime_ns:
                try:
                    definitions = self._load_path(path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise HTTPException(status_code=503, detail="动态查询 Provider 目录无效") from exc
                self._path = path
                self._mtime_ns = stat.st_mtime_ns
                self._definitions = definitions
            definition = self._definitions.get(command_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="动态查询命令未在接口端配置")
        return definition


_catalog = DynamicProviderCatalog()
_session = requests.Session()


def normalize_dynamic_parameters(value: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if key == "command_id":
            continue
        text = str(raw_value or "").strip()
        if not key or not text:
            continue
        if not _PARAMETER_KEY_RE.fullmatch(key):
            raise HTTPException(status_code=400, detail="动态查询参数名无效")
        if len(text) > 1000:
            raise HTTPException(status_code=400, detail="动态查询参数过长")
        result[key] = text
    if len(result) > 32:
        raise HTTPException(status_code=400, detail="动态查询参数过多")
    return result


def _replace_tokens(value: str, parameters: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(parameters.get(key) or "")

    return _TOKEN_RE.sub(replace, str(value or ""))


def _replace_map(value: Mapping[str, str], parameters: Mapping[str, str]) -> Dict[str, str]:
    return {key: _replace_tokens(item, parameters) for key, item in value.items()}


def _build_url(definition: DynamicProviderDefinition, parameters: Mapping[str, str]) -> str:
    raw_url = _replace_tokens(definition.url, parameters)
    parts = urlsplit(raw_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(_replace_map(definition.query, parameters))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _blocked_address(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return bool(
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _validate_destination(url: str, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise HTTPException(status_code=503, detail="动态 Provider 地址无效")
    if parts.username or parts.password:
        raise HTTPException(status_code=503, detail="动态 Provider 地址禁止内嵌凭据")
    host = parts.hostname.lower()
    if allow_private:
        return
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(status_code=503, detail="动态 Provider 禁止访问本机或私网")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise HTTPException(status_code=503, detail="动态 Provider 域名解析失败") from exc
    if not addresses or any(_blocked_address(address) for address in addresses):
        raise HTTPException(status_code=503, detail="动态 Provider 禁止访问本机或私网")


def _extract_path(value: Any, path: str) -> Any:
    if not path:
        return value
    current = value
    for match in _PATH_TOKEN_RE.finditer(path):
        key, index_text = match.groups()
        if key is not None:
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        else:
            index = int(index_text)
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def _normalize_result(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value).strip()


def _snapshot_source(command_id: str, parameters: Mapping[str, str]) -> str:
    canonical = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{command_id}\n{canonical}".encode("utf-8")).hexdigest()[:24]
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", command_id)[:60]
    return f"dynamic.{safe_id}.{digest}"


def _execute_provider(definition: DynamicProviderDefinition, parameters: Mapping[str, str]) -> str:
    url = _build_url(definition, parameters)
    _validate_destination(url, definition.allow_private)
    headers = _replace_map(definition.headers, parameters)
    body = _replace_map(definition.body, parameters)
    timeout_seconds = definition.timeout_ms / 1000.0
    last_error = ""
    for attempt in range(2):
        response: Optional[requests.Response] = None
        try:
            response = _session.request(
                definition.method,
                url,
                headers=headers or None,
                json=body if definition.method == "POST" and body else None,
                timeout=(min(3.0, timeout_seconds), timeout_seconds),
            )
            if response.status_code in _RETRYABLE_STATUS and attempt == 0:
                time.sleep(0.2)
                continue
            if not response.ok:
                raise RuntimeError(f"provider_http_{response.status_code}")
            raw_text = response.text.strip()
            try:
                decoded: Any = response.json()
                is_json = True
            except ValueError:
                decoded = raw_text
                is_json = False
            if is_json and not definition.text_path:
                raise RuntimeError("provider_text_path_required")
            extracted = _extract_path(decoded, definition.text_path) if is_json else decoded
            result = _normalize_result(extracted)
            if not result:
                raise RuntimeError("provider_empty_response")
            return result[:20000]
        except (requests.RequestException, RuntimeError) as exc:
            last_error = str(exc)[:120]
            if attempt == 0:
                time.sleep(0.2)
                continue
        finally:
            if response is not None:
                response.close()
    raise RuntimeError(last_error or "provider_unavailable")


async def query_dynamic(ctx: Any, command_id: str, raw_parameters: Mapping[str, Any]) -> Dict[str, Any]:
    normalized_id = str(command_id or "").strip()
    if not _COMMAND_ID_RE.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="动态命令 id 无效")
    parameters = normalize_dynamic_parameters(raw_parameters)
    definition = _catalog.get(normalized_id)
    source_id = _snapshot_source(normalized_id, parameters)
    try:
        text = await asyncio.to_thread(_execute_provider, definition, parameters)
        payload = {
            "command_id": normalized_id,
            "text": text,
            "source": "live",
            "is_stale": False,
            "snapshot_updated_at": "",
        }
        if definition.snapshot_seconds > 0:
            ctx.upstream_snapshot_store.save(
                source_id,
                payload,
                metadata={"feature": "dynamic", "command_id": normalized_id},
            )
        return payload
    except HTTPException:
        raise
    except Exception:
        if definition.snapshot_seconds > 0:
            snapshot = ctx.upstream_snapshot_store.load(source_id, max_age_seconds=definition.snapshot_seconds)
            if snapshot.ok and isinstance(snapshot.payload, Mapping):
                text = str(snapshot.payload.get("text") or "").strip()
                if text:
                    return {
                        "command_id": normalized_id,
                        "text": text[:20000],
                        "source": "snapshot",
                        "is_stale": True,
                        "snapshot_updated_at": snapshot.captured_at,
                    }
        raise HTTPException(status_code=503, detail=definition.fallback_text)


def format_dynamic_text(payload: Mapping[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if bool(payload.get("is_stale")):
        return f"{text}\n\n数据状态：当前使用接口端最近有效结果"
    return text


def dynamic_meta(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "command_id": str(payload.get("command_id") or ""),
        "source": str(payload.get("source") or ""),
        "stale": bool(payload.get("is_stale")),
        "updated_at": str(payload.get("snapshot_updated_at") or ""),
    }
