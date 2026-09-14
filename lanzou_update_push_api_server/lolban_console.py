from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import management
from .control_ui import render_lolban_console_page
from .parser_center_admin import _load_effective_config, save_parser_center, save_parser_secret


_MAX_MAIN_RESPONSE_BYTES = 2_000_000
_MASK = "***"
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|cookie|api[_-]?key|access[_-]?key)",
    re.I,
)
_LOLBAN_ENV_FIELDS: list[dict[str, Any]] = [
    {"key": "LOL_BAN_UPSTREAM_URL", "label": "旧版封号上游 URL", "section": "封号查询", "type": "text"},
    {"key": "LOL_BAN_MAX_STALE_ENTRIES", "label": "最近成功结果最大条数", "section": "封号查询", "type": "int", "min": 1, "max": 100000},
    {"key": "LOL_BAN_SNAPSHOT_ENABLED", "label": "持久化快照启用", "section": "封号查询", "type": "bool"},
]
_LOLBAN_SETTING_KEYS = (
    "LOL_BAN_TIMEOUT",
    "LOL_BAN_NORMAL_CACHE_SECONDS",
    "LOL_BAN_BANNED_CACHE_SECONDS",
    "LOL_BAN_STALE_CACHE_SECONDS",
    "LOL_BAN_MAX_STALE_ENTRIES",
    "LOL_BAN_SNAPSHOT_ENABLED",
)
_LOLBAN_RELOAD_KEYS = (
    "LOL_BAN_PROVIDERS_JSON",
    "LOL_BAN_UPSTREAM_URL",
    *_LOLBAN_SETTING_KEYS,
    "LOLMAP_API_TOKEN",
    "LOL_BAN_4PNG_TOKEN",
)
_LOLBAN_PROVIDER_SECRET_SPECS: dict[str, dict[str, str]] = {
    "lolban-primary": {
        "name": "LOLMAP_API_TOKEN",
        "label": "主接口 Token",
    },
    "lolban-4png": {
        "name": "LOL_BAN_4PNG_TOKEN",
        "label": "4PNG Token",
    },
}


def _ensure_fields() -> None:
    for spec in _LOLBAN_ENV_FIELDS:
        if spec["key"] in management._FIELD_BY_KEY:
            continue
        management.MAIN_CONFIG_FIELDS.append(spec)
        management._FIELD_BY_KEY[spec["key"]] = spec


def _file_env_values() -> dict[str, str]:
    source_text, _source = management._read_env_source()
    return management._parse_env_values(source_text)


def _effective_env_value(key: str, file_values: Mapping[str, str]) -> str:
    if key in file_values:
        return str(file_values.get(key) or "")
    return str(os.getenv(key) or "")


def _parse_provider_json(raw: str) -> tuple[list[dict[str, Any]], str]:
    text = str(raw or "").strip()
    if not text:
        return [], ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"LOL_BAN_PROVIDERS_JSON 不是有效 JSON：{exc.msg}"
    if not isinstance(value, list):
        return [], "LOL_BAN_PROVIDERS_JSON 必须是数组"
    return [copy.deepcopy(item) for item in value if isinstance(item, dict)], ""


def _redact_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
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
            query.append((key, _MASK if _SENSITIVE_KEY_RE.search(key) else item))
        fragment = _MASK if _SENSITIVE_KEY_RE.search(parts.fragment) else parts.fragment
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), fragment))
    except Exception:
        return _MASK


def _merge_masked_url(value: Any, previous: Any) -> str:
    current_text = str(value or "").strip()
    previous_text = str(previous or "").strip()
    if current_text == _MASK:
        return previous_text
    if _MASK not in current_text or not previous_text:
        return current_text
    try:
        current = urlsplit(current_text)
        old = urlsplit(previous_text)
    except ValueError:
        return previous_text if current_text == _redact_url(previous_text) else current_text
    if (current.scheme, current.hostname, current.port, current.path) != (
        old.scheme,
        old.hostname,
        old.port,
        old.path,
    ):
        return current_text

    old_query: dict[str, list[str]] = {}
    for key, item in parse_qsl(old.query, keep_blank_values=True):
        old_query.setdefault(key, []).append(item)
    counters: dict[str, int] = {}
    merged_query: list[tuple[str, str]] = []
    for key, item in parse_qsl(current.query, keep_blank_values=True):
        index = counters.get(key, 0)
        counters[key] = index + 1
        if item == _MASK and index < len(old_query.get(key, [])):
            item = old_query[key][index]
        merged_query.append((key, item))

    username = current.username
    password = current.password
    if username == _MASK:
        username = old.username
        password = old.password
    hostname = current.hostname or ""
    netloc = hostname
    if current.port:
        netloc = f"{netloc}:{current.port}"
    if username is not None:
        credentials = username
        if password is not None:
            credentials = f"{credentials}:{password}"
        netloc = f"{credentials}@{netloc}"
    fragment = old.fragment if current.fragment == _MASK else current.fragment
    return urlunsplit((current.scheme, netloc, current.path, urlencode(merged_query), fragment))


def _redact(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str) and value.strip().startswith("$secret:"):
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
    return copy.deepcopy(value)


def _merge_masked(value: Any, previous: Any, *, key: str = "") -> Any:
    if str(key).lower() in {"url", "endpoint", "request_url", "provider_url"}:
        return _merge_masked_url(value, previous)
    if value == _MASK:
        return copy.deepcopy(previous)
    if isinstance(value, Mapping):
        old = previous if isinstance(previous, Mapping) else {}
        return {
            str(item_key): _merge_masked(item, old.get(item_key), key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        old_list = previous if isinstance(previous, list) else []
        return [
            _merge_masked(item, old_list[index] if index < len(old_list) else None)
            for index, item in enumerate(value)
        ]
    return copy.deepcopy(value)


def _provider_key(provider: Mapping[str, Any], index: int) -> str:
    return str(provider.get("id") or provider.get("name") or f"provider-{index}").strip()


def _merge_provider_list(submitted: list[Any], previous: list[Any]) -> list[dict[str, Any]]:
    old_items = [item for item in previous if isinstance(item, Mapping)]
    old_by_key = {
        _provider_key(item, index): item
        for index, item in enumerate(old_items, start=1)
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(submitted, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Provider {index} 必须是对象")
        key = _provider_key(item, index)
        previous_item = old_by_key.get(key)
        if previous_item is None and index <= len(old_items):
            previous_item = old_items[index - 1]
        merged = _merge_masked(dict(item), previous_item or {})
        result.append(dict(merged))
    return result


def _canonical_provider_url(value: Any) -> str:
    return str(value or "").strip().replace("{qq}", "$qq")


def _provider_identity(provider: Mapping[str, Any], index: int) -> dict[str, Any]:
    request = provider.get("request") if isinstance(provider.get("request"), Mapping) else provider
    return {
        "order": index,
        "id": _provider_key(provider, index),
        "enabled": provider.get("enabled") is not False,
        "method": str(request.get("method") or "GET").upper(),
        "url": _canonical_provider_url(request.get("url") or provider.get("url")),
    }


def _provider_signature(providers: list[dict[str, Any]]) -> str:
    stable = json.dumps(providers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _main_headers() -> dict[str, str]:
    token = str(os.getenv("GROUPGUARD_WRITE_TOKEN") or os.getenv("WEBUI_ADMIN_TOKEN") or "").strip()
    headers = {"accept": "application/json"}
    if token:
        headers["x-groupguard-token"] = token
    return headers


def _read_bounded_response(response: requests.Response) -> bytes:
    declared = str(response.headers.get("content-length") or "").strip()
    if declared:
        try:
            if int(declared) > _MAX_MAIN_RESPONSE_BYTES:
                raise ValueError("response_too_large")
        except ValueError as exc:
            if str(exc) == "response_too_large":
                raise
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > _MAX_MAIN_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _main_request(
    main_base_url: str,
    method: str,
    path: str,
    *,
    payload: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response: requests.Response | None = None
    try:
        response = requests.request(
            method,
            f"{main_base_url.rstrip('/')}{path}",
            headers={**_main_headers(), "content-type": "application/json"},
            json=dict(payload) if payload is not None else None,
            params=dict(params) if params is not None else None,
            timeout=(3.0, 30.0),
            stream=True,
        )
        try:
            body = _read_bounded_response(response)
        except ValueError:
            return {"ok": False, "status_code": response.status_code, "error": "response_too_large"}
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            decoded = {"ok": False, "error": body.decode("utf-8", errors="replace")[:4000]}
        if not isinstance(decoded, dict):
            decoded = {"ok": response.ok, "data": decoded}
        decoded.setdefault("ok", response.ok)
        decoded["status_code"] = response.status_code
        return _redact(decoded)
    except requests.RequestException as exc:
        return {"ok": False, "status_code": 0, "error": type(exc).__name__}
    finally:
        if response is not None:
            response.close()


def _disk_state() -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    config, target, using_default = _load_effective_config()
    features = config.get("features") if isinstance(config.get("features"), Mapping) else {}
    lolban = features.get("lolban") if isinstance(features.get("lolban"), Mapping) else {}
    parser_providers = lolban.get("providers") if isinstance(lolban.get("providers"), list) else []
    file_values = _file_env_values()
    legacy_raw = _effective_env_value("LOL_BAN_PROVIDERS_JSON", file_values)
    legacy_providers, legacy_error = _parse_provider_json(legacy_raw)
    legacy_url = _effective_env_value("LOL_BAN_UPSTREAM_URL", file_values)
    settings = {key: _effective_env_value(key, file_values) for key in _LOLBAN_SETTING_KEYS}

    active: list[dict[str, Any]] = []
    for provider in parser_providers:
        if isinstance(provider, Mapping) and provider.get("enabled") is not False:
            active.append(_provider_identity(provider, len(active) + 1))
    for provider in legacy_providers:
        if provider.get("enabled") is not False:
            active.append(_provider_identity(provider, len(active) + 1))
    if legacy_url.strip():
        active.append(
            {
                "order": len(active) + 1,
                "id": "legacy-form",
                "enabled": True,
                "method": "POST",
                "url": _canonical_provider_url(legacy_url),
            }
        )

    public = {
        "parser_center": {
            "path": str(target),
            "using_default": using_default,
            "providers": _redact(parser_providers),
        },
        "legacy": {
            "path": str(management.APP_ENV_PATH),
            "providers": _redact(legacy_providers),
            "upstream_url": _redact_url(legacy_url),
            "error": legacy_error,
        },
        "settings": settings,
        "active_provider_identity": [_redact(item) for item in active],
        "provider_signature": _provider_signature(active),
    }
    raw = {
        "config": config,
        "parser_providers": parser_providers,
        "legacy_providers": legacy_providers,
        "legacy_url": legacy_url,
    }
    return public, file_values, raw


def _runtime_identity(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    providers = runtime.get("providers") if isinstance(runtime.get("providers"), list) else []
    result: list[dict[str, Any]] = []
    for index, provider in enumerate(providers, start=1):
        if not isinstance(provider, Mapping):
            continue
        request = provider.get("request") if isinstance(provider.get("request"), Mapping) else {}
        result.append(
            {
                "order": index,
                "id": str(provider.get("id") or provider.get("name") or f"provider-{index}"),
                "enabled": True,
                "method": str(request.get("method") or "GET").upper(),
                "url": _canonical_provider_url(request.get("url")),
            }
        )
    return result


def read_lolban_console(main_base_url: str) -> dict[str, Any]:
    disk, _file_values, _raw = _disk_state()
    runtime = _main_request(main_base_url, "GET", "/admin/query/lolban/runtime")
    runtime_identity = _runtime_identity(runtime)
    disk_identity = disk.get("active_provider_identity") or []
    safe_runtime_identity = [_redact(item) for item in runtime_identity]
    runtime_secret_states: dict[str, bool] = {}
    for secret in runtime.get("secrets") if isinstance(runtime.get("secrets"), list) else []:
        if not isinstance(secret, Mapping):
            continue
        name = str(secret.get("name") or "").strip()
        if name:
            runtime_secret_states[name] = bool(secret.get("configured"))

    provider_secrets: dict[str, dict[str, Any]] = {}
    for provider_id, spec in _LOLBAN_PROVIDER_SECRET_SPECS.items():
        name = spec["name"]
        disk_value = str(_file_values.get(name) or os.getenv(name) or "").strip()
        disk_configured = bool(disk_value and disk_value != "CHANGE_ME")
        runtime_configured = bool(runtime_secret_states.get(name))
        provider_secrets[provider_id] = {
            "label": spec["label"],
            "secret_name": name,
            "disk_configured": disk_configured,
            "runtime_configured": runtime_configured,
            "in_sync": disk_configured == runtime_configured,
        }

    return {
        "ok": True,
        "disk": disk,
        "runtime": runtime,
        "runtime_provider_identity": safe_runtime_identity,
        "runtime_matches_disk": runtime.get("ok") is True and safe_runtime_identity == disk_identity,
        "provider_secrets": provider_secrets,
        "fourpng_secret": provider_secrets["lolban-4png"],
    }


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "message": str(result.get("message") or ""),
        "backup_path": str(result.get("backup_path") or ""),
        "restart_required": bool(result.get("restart_required")),
    }


def save_lolban_console(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    parser_submitted = payload.get("parser_providers")
    legacy_submitted = payload.get("legacy_providers")
    settings = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else {}
    if not isinstance(parser_submitted, list) or not isinstance(legacy_submitted, list):
        raise ValueError("parser_providers 和 legacy_providers 必须是数组")

    _public, _file_values, raw = _disk_state()
    config = copy.deepcopy(raw["config"])
    features = config.setdefault("features", {})
    lolban = features.setdefault("lolban", {"operation": "query", "providers": []})
    lolban["operation"] = "query"
    parser_providers = _merge_provider_list(parser_submitted, raw["parser_providers"])
    lolban["providers"] = parser_providers
    parser_result = save_parser_center({"config": config})

    legacy_providers = _merge_provider_list(legacy_submitted, raw["legacy_providers"])
    legacy_url = _merge_masked_url(payload.get("legacy_upstream_url"), raw["legacy_url"])
    _ensure_fields()
    env_patch: dict[str, Any] = {
        "LOL_BAN_PROVIDERS_JSON": json.dumps(legacy_providers, ensure_ascii=False, separators=(",", ":")),
        "LOL_BAN_UPSTREAM_URL": legacy_url,
    }
    for key in _LOLBAN_SETTING_KEYS:
        if key in settings:
            env_patch[key] = settings[key]
    env_result = management.update_main_config(env_patch)

    final_values = _file_env_values()
    reload_environment = {
        key: str(final_values.get(key, os.getenv(key, "")) or "")
        for key in _LOLBAN_RELOAD_KEYS
    }
    reload_result = _main_request(
        main_base_url,
        "POST",
        "/admin/query/lolban/reload",
        payload={"environment": reload_environment},
    )
    return {
        "ok": reload_result.get("ok") is True,
        "message": (
            "封号查询配置已保存并热加载到 5001。"
            if reload_result.get("ok") is True
            else "配置已保存，但 5001 热加载失败；请查看运行态诊断。"
        ),
        "parser_result": _result_summary(parser_result),
        "environment_result": _result_summary(env_result),
        "reload_result": reload_result,
        "state": read_lolban_console(main_base_url),
    }


def save_provider_secret(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = str(payload.get("provider_id") or "").strip()
    spec = _LOLBAN_PROVIDER_SECRET_SPECS.get(provider_id)
    if spec is None:
        raise ValueError("该 Provider 没有可配置的专用 Secret")
    value = str(payload.get("value") or "").strip()
    if not value:
        raise ValueError(f"{spec['label']} 不能为空")

    secret_name = spec["name"]
    saved = save_parser_secret({"name": secret_name, "value": value})
    reload_result = _main_request(
        main_base_url,
        "POST",
        "/admin/query/lolban/reload",
        payload={"environment": {secret_name: value}},
    )
    loaded = reload_result.get("ok") is True
    return {
        "ok": loaded,
        "provider_id": provider_id,
        "configured": True,
        "runtime_configured": loaded,
        "message": (
            f"{spec['label']} 已安全保存并热加载到 5001。"
            if loaded
            else f"{spec['label']} 已安全保存，但 5001 热加载失败；请重启 LOLDataSystem。"
        ),
        "save_result": _result_summary(saved),
        "reload_result": reload_result,
    }


def save_fourpng_token(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return save_provider_secret(
        main_base_url,
        {"provider_id": "lolban-4png", "value": payload.get("value")},
    )


def test_lolban_console(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    qq = str(payload.get("qq") or "").strip()
    provider_id = str(payload.get("provider_id") or "").strip()
    mode = str(payload.get("mode") or "both").strip().lower()
    if mode not in {"provider", "formal", "both"}:
        raise ValueError("mode 必须是 provider、formal 或 both")
    result: dict[str, Any] = {"ok": True, "mode": mode}
    if mode in {"provider", "both"}:
        provider_result = _main_request(
            main_base_url,
            "POST",
            "/admin/query/lolban/provider-test",
            payload={"qq": qq, "provider_id": provider_id},
        )
        result["provider_test"] = provider_result
        result["ok"] = result["ok"] and provider_result.get("ok") is True
    if mode in {"formal", "both"}:
        formal_result = _main_request(
            main_base_url,
            "GET",
            "/api/v2/lolban",
            params={"qq": qq, "output": "json"},
        )
        result["formal_chain"] = formal_result
        result["ok"] = result["ok"] and formal_result.get("ok") is True
    return result


def install_lolban_console_routes(app: FastAPI) -> None:
    @app.get("/query-console/lolban", response_class=HTMLResponse)
    async def lolban_console_page() -> str:
        return render_lolban_console_page()

    @app.get("/admin/query-console/lolban")
    async def admin_lolban_console() -> dict[str, Any]:
        return await asyncio.to_thread(read_lolban_console, app.state.main_base_url)

    @app.post("/admin/query-console/lolban/save")
    async def admin_lolban_console_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_lolban_console, app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"封号查询配置写入失败：{exc}") from exc

    @app.post("/admin/query-console/lolban/provider-secret")
    async def admin_lolban_provider_secret(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_provider_secret, app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Provider Token 写入失败：{exc}") from exc

    @app.post("/admin/query-console/lolban/4png-token")
    async def admin_lolban_fourpng_token(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_fourpng_token, app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"4PNG Token 写入失败：{exc}") from exc

    @app.post("/admin/query-console/lolban/test")
    async def admin_lolban_console_test(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(test_lolban_console, app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
