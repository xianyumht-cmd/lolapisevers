from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
from typing import Any, Dict, Mapping, Tuple
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, parse_qsl

from fastapi import HTTPException


_VIDEO_KEYS = (
    "url",
    "video",
    "video_url",
    "play",
    "play_url",
    "src",
    "link",
    "mp4",
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def load_video_provider_templates() -> Dict[str, str]:
    raw = str(
        os.getenv("QUERY_VIDEO_PROVIDERS_JSON")
        or os.getenv("VIDEO_PROVIDER_TEMPLATES_JSON")
        or ""
    ).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("QUERY_VIDEO_PROVIDERS_JSON 不是有效 JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("QUERY_VIDEO_PROVIDERS_JSON 必须是分类到URL模板的对象")
    result: Dict[str, str] = {}
    for key, value in parsed.items():
        category = str(key or "").strip()
        template = str(value or "").strip()
        if not category or not template:
            continue
        parts = urlsplit(template.replace("{category}", "sample"))
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"视频 Provider 模板无效：{category}")
        result[category] = template
    return result


def _pick_template(templates: Mapping[str, str], category: str) -> Tuple[str, str]:
    if category in templates:
        return category, templates[category]
    if not templates:
        raise HTTPException(status_code=503, detail="视频查询 Provider 尚未在接口端配置")
    first = next(iter(templates))
    return first, templates[first]


def build_video_request_url(template: str, category: str) -> str:
    value = str(template or "").strip()
    if "{category}" in value:
        return value.replace("{category}", quote(category, safe=""))
    parts = urlsplit(value)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["category"] = category
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _candidate_values(data: Any):
    if isinstance(data, str):
        yield data
        return
    if isinstance(data, Mapping):
        for key in _VIDEO_KEYS:
            if key in data:
                yield data.get(key)
        for container in ("data", "result"):
            nested = data.get(container)
            if isinstance(nested, Mapping):
                for key in _VIDEO_KEYS:
                    if key in nested:
                        yield nested.get(key)


def _is_public_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return False
        host = parts.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    except Exception:
        return False


def extract_video_url(data: Any, raw_text: str = "") -> str:
    for candidate in _candidate_values(data):
        text = str(candidate or "").strip()
        if _is_public_http_url(text):
            return text
    for match in _URL_RE.findall(str(raw_text or "")):
        text = match.rstrip(".,;，。；)")
        if _is_public_http_url(text):
            return text
    return ""


def _snapshot_source(category: str) -> str:
    digest = hashlib.sha256(category.encode("utf-8")).hexdigest()[:20]
    return f"video.{digest}"


async def query_video(ctx: Any, category: str) -> Dict[str, Any]:
    normalized_category = str(category or "").strip() or "热门"
    if len(normalized_category) > 64:
        raise HTTPException(status_code=400, detail="视频分类过长")
    try:
        templates = load_video_provider_templates()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    provider_key, template = _pick_template(templates, normalized_category)
    request_url = build_video_request_url(template, normalized_category)
    source_id = _snapshot_source(normalized_category)
    response = await asyncio.to_thread(
        ctx.upstream_http_client.request,
        f"video_provider_{hashlib.sha256(provider_key.encode('utf-8')).hexdigest()[:12]}",
        request_url,
        parse_json=False,
        attempts=2,
        read_timeout=10.0,
        singleflight=True,
    )
    if response.ok:
        raw_text = str(response.text or "")
        parsed: Any = raw_text
        try:
            parsed = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            parsed = raw_text
        direct_url = extract_video_url(parsed, raw_text)
        if direct_url:
            payload = {
                "category": normalized_category,
                "url": direct_url,
                "source": "live",
                "is_stale": False,
                "snapshot_updated_at": "",
                "provider": provider_key,
            }
            ctx.upstream_snapshot_store.save(
                source_id,
                payload,
                metadata={"feature": "video", "category": normalized_category},
            )
            return payload

    snapshot = ctx.upstream_snapshot_store.load(source_id, max_age_seconds=86400)
    if snapshot.ok and isinstance(snapshot.payload, Mapping):
        direct_url = str(snapshot.payload.get("url") or "").strip()
        if _is_public_http_url(direct_url):
            return {
                "category": normalized_category,
                "url": direct_url,
                "source": "snapshot",
                "is_stale": True,
                "snapshot_updated_at": snapshot.captured_at,
                "provider": str(snapshot.payload.get("provider") or provider_key),
            }

    raise HTTPException(status_code=503, detail="视频查询服务暂不可用，请稍后再试")


def format_video_text(payload: Mapping[str, Any]) -> str:
    category = str(payload.get("category") or "热门").strip()
    direct_url = str(payload.get("url") or "").strip()
    lines = [f"🎬 {category} 视频", direct_url]
    if bool(payload.get("is_stale")):
        lines.append("数据状态：当前使用接口端最近有效结果")
    return "\n".join(lines).strip()


def video_meta(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "source": str(payload.get("source") or ""),
        "stale": bool(payload.get("is_stale")),
        "updated_at": str(payload.get("snapshot_updated_at") or ""),
        "category": str(payload.get("category") or ""),
        "provider": str(payload.get("provider") or ""),
    }
