from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from fastapi import APIRouter, HTTPException, Request

from services import lolban_service
from services.api_parser_center import ParserConfigError, ProviderResponseError, prepare_request
from services.main_control_security import require_control_access


router = APIRouter()
_RUNTIME_LOADED_AT = datetime.now(timezone.utc).isoformat()
_MASK = "***"
_SECRET_REF_RE = re.compile(r"^\$secret:([A-Za-z_][A-Za-z0-9_]*)$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|cookie|api[_-]?key|access[_-]?key)",
    re.I,
)
_ALLOWED_RELOAD_ENV_KEYS = {
    "LOL_BAN_PROVIDERS_JSON",
    "LOL_BAN_UPSTREAM_URL",
    "LOL_BAN_TIMEOUT",
    "LOL_BAN_NORMAL_CACHE_SECONDS",
    "LOL_BAN_BANNED_CACHE_SECONDS",
    "LOL_BAN_STALE_CACHE_SECONDS",
    "LOL_BAN_MAX_STALE_ENTRIES",
    "LOL_BAN_SNAPSHOT_ENABLED",
    "LOLMAP_API_TOKEN",
    "LOL_BAN_4PNG_TOKEN",
}


def _secret_configured(name: str) -> bool:
    value = str(os.getenv(name) or "").strip()
    return bool(value and value != "CHANGE_ME")


def _secret_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            names.update(_secret_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.update(_secret_names(item))
    elif isinstance(value, str):
        match = _SECRET_REF_RE.fullmatch(value.strip())
        if match:
            names.add(match.group(1))
    return names


def _redact_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if not parts.scheme or not parts.netloc:
        return text
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username is not None or parts.password is not None:
        netloc = f"{_MASK}@{netloc}"
    query: list[tuple[str, str]] = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if _SECRET_REF_RE.fullmatch(item.strip()):
            query.append((key, item))
        else:
            query.append((key, _MASK if _SENSITIVE_KEY_RE.search(key) else item))
    fragment = _MASK if _SENSITIVE_KEY_RE.search(parts.fragment) else parts.fragment
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), fragment))


def _redact(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str) and _SECRET_REF_RE.fullmatch(value.strip()):
        return value
    if str(key).lower() in {"url", "endpoint", "request_url", "provider_url"}:
        return _redact_url(value)
    if _SENSITIVE_KEY_RE.search(str(key or "")):
        return _MASK
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return copy.deepcopy(value)


def _provider_profile(provider: Any, index: int) -> dict[str, Any]:
    method = str(getattr(provider, "method", "GET") or "GET").upper()
    url = str(getattr(provider, "url", "") or "")
    qq_param = str(getattr(provider, "qq_param", "qq") or "qq")
    query = dict(getattr(provider, "query_params", {}) or {})
    form = dict(getattr(provider, "form", {}) or {})
    json_body = copy.deepcopy(getattr(provider, "json_body", None))
    if "$qq" not in url and "{qq}" not in url:
        if method == "GET" and qq_param not in query:
            query[qq_param] = "$qq"
        elif method != "GET" and qq_param not in form:
            form[qq_param] = "$qq"
    return {
        "id": str(getattr(provider, "name", "") or f"provider-{index}"),
        "name": str(getattr(provider, "name", "") or f"provider-{index}"),
        "enabled": True,
        "request": {
            "method": method,
            "url": url.replace("{qq}", "$qq"),
            "headers": dict(getattr(provider, "headers", {}) or {}),
            "query": query,
            "form": form,
            "json": json_body,
            "timeout_seconds": float(getattr(provider, "timeout_seconds", 10.0) or 10.0),
        },
        "parser": copy.deepcopy(dict(getattr(provider, "parser", {}) or {})),
    }


def _provider_snapshot(provider: Any, index: int) -> dict[str, Any]:
    profile = _provider_profile(provider, index)
    secret_names = sorted(_secret_names(profile))
    redacted = _redact(profile)
    redacted["order"] = index
    redacted["secrets"] = [
        {"name": name, "configured": _secret_configured(name)}
        for name in secret_names
    ]
    return redacted


def _signature(providers: list[dict[str, Any]]) -> str:
    stable = json.dumps(providers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def lolban_runtime_snapshot() -> dict[str, Any]:
    service = lolban_service._default_service
    providers = [
        _provider_snapshot(provider, index)
        for index, provider in enumerate(service.providers, start=1)
    ]
    return {
        "ok": True,
        "loaded_at": _RUNTIME_LOADED_AT,
        "provider_count": len(providers),
        "providers": providers,
        "provider_signature": _signature(providers),
        "secrets": [
            {"name": "LOLMAP_API_TOKEN", "configured": _secret_configured("LOLMAP_API_TOKEN")},
            {"name": "LOL_BAN_4PNG_TOKEN", "configured": _secret_configured("LOL_BAN_4PNG_TOKEN")},
        ],
        "health": service.health(),
    }


def _select_provider(provider_id: str) -> tuple[Any, int]:
    service = lolban_service._default_service
    providers = list(service.providers)
    if not providers:
        raise HTTPException(status_code=503, detail="封号查询没有已加载的 Provider")
    requested = str(provider_id or "").strip()
    if not requested:
        return providers[0], 1
    for index, provider in enumerate(providers, start=1):
        if str(getattr(provider, "name", "") or "") == requested:
            return provider, index
    raise HTTPException(status_code=404, detail="指定的封号 Provider 未在当前运行时加载")


def _request_preview(provider: Any, index: int, qq: str) -> dict[str, Any]:
    profile = _provider_profile(provider, index)
    prepared = prepare_request(profile, {"qq": qq})
    return _redact(prepared.redacted())


def _apply_reload_environment(payload: Mapping[str, Any]) -> list[str]:
    supplied = payload.get("environment")
    if supplied is None:
        return []
    if not isinstance(supplied, Mapping):
        raise HTTPException(status_code=400, detail="environment 必须是对象")
    changed: list[str] = []
    for raw_key, raw_value in supplied.items():
        key = str(raw_key or "").strip()
        if key not in _ALLOWED_RELOAD_ENV_KEYS:
            raise HTTPException(status_code=400, detail=f"不允许热加载环境字段：{key}")
        os.environ[key] = str(raw_value if raw_value is not None else "")
        changed.append(key)
    return changed


def _reload_lolban_module() -> None:
    importlib.reload(lolban_service)


def _provider_error_diagnostic(exc: Exception) -> dict[str, Any]:
    text = str(exc or "")
    lowered = text.lower()
    if isinstance(exc, ParserConfigError):
        if "secret" in lowered and "未配置" in text:
            return {
                "category": "secret_not_loaded",
                "message": "Provider 引用的 Secret 尚未加载到 5001。请重新保存 Token 并确认热加载成功。",
            }
        return {
            "category": "provider_config_invalid",
            "message": "Provider 请求配置无法生成，请检查 URL、参数映射和 Secret 引用。",
        }
    if isinstance(exc, ProviderResponseError):
        if any(word in lowered for word in ("unsafe", "广告", "推广", "充值", "购买")):
            return {
                "category": "promotion_blocked",
                "message": "上游返回了推广或不安全内容，已拦截并判定此 Provider 失败。",
                "status_code": int(getattr(exc, "status_code", 502) or 502),
            }
        return {
            "category": "upstream_business_rejected",
            "message": "上游业务响应未通过成功条件，可能是 Token、额度、状态码或响应结构不符合预期。",
            "status_code": int(getattr(exc, "status_code", 502) or 502),
        }
    if isinstance(exc, requests.Timeout):
        return {"category": "timeout", "message": "连接上游超时。"}
    if isinstance(exc, requests.ConnectionError):
        return {"category": "network_error", "message": "无法连接上游接口。"}
    if "json" in lowered or "payload" in lowered or "response" in lowered:
        return {"category": "response_invalid", "message": "上游响应无法按当前解析规则处理。"}
    return {"category": "provider_failed", "message": "Provider 直连失败，未向用户公开上游原始错误。"}


@router.get("/admin/query/lolban/runtime")
async def admin_lolban_runtime(request: Request) -> dict[str, Any]:
    require_control_access(request)
    return await asyncio.to_thread(lolban_runtime_snapshot)


@router.post("/admin/query/lolban/provider-test")
async def admin_lolban_provider_test(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    require_control_access(request)
    qq = str(payload.get("qq") or "").strip()
    if not lolban_service.valid_qq(qq):
        raise HTTPException(status_code=400, detail="请输入有效的QQ号（5-11位数字）")
    provider, index = _select_provider(str(payload.get("provider_id") or ""))
    preview: dict[str, Any] = {}
    started = datetime.now(timezone.utc)
    try:
        preview = _request_preview(provider, index, qq)
        result = await asyncio.to_thread(provider.query, qq)
    except Exception as exc:
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        diagnostic = _provider_error_diagnostic(exc)
        response = {
            "ok": False,
            "provider": _provider_snapshot(provider, index),
            "request": preview,
            "elapsed_ms": elapsed_ms,
            "error_class": type(exc).__name__,
            "error_category": diagnostic.get("category"),
            "diagnostic": diagnostic.get("message"),
            "error": "Provider 直连失败",
        }
        if "status_code" in diagnostic:
            response["upstream_status_code"] = diagnostic["status_code"]
        return response
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "ok": True,
        "provider": _provider_snapshot(provider, index),
        "request": preview,
        "elapsed_ms": elapsed_ms,
        "result": _redact(result),
    }


@router.post("/admin/query/lolban/reload")
async def admin_lolban_reload(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    require_control_access(request)
    changed_environment = _apply_reload_environment(payload or {})
    global _RUNTIME_LOADED_AT
    try:
        await asyncio.to_thread(_reload_lolban_module)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"封号 Provider 重新加载失败：{type(exc).__name__}",
        ) from exc
    _RUNTIME_LOADED_AT = datetime.now(timezone.utc).isoformat()
    snapshot = lolban_runtime_snapshot()
    snapshot["reloaded"] = True
    snapshot["changed_environment"] = changed_environment
    return snapshot
