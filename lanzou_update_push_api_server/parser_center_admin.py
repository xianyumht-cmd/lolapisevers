from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from services.api_parser_center import (
    CONFIG_SCHEMA,
    DEFAULT_CONFIG_PATH,
    ParserCenterError,
    ParserConfigError,
    atomic_write_config,
    configured_path,
    empty_config,
    find_provider,
    load_config,
    redact,
    test_provider,
    validate_config,
)

from .parser_center_ui import render_parser_center_page


_SECRET_REF_RE = re.compile(r"^\$secret:([A-Za-z_][A-Za-z0-9_]*)$")
_DEFAULT_PROFILE_PATH = DEFAULT_CONFIG_PATH.with_name("interface-parser-center.default.json")


def _walk_secret_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            names.update(_walk_secret_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_walk_secret_names(item))
    elif isinstance(value, str):
        match = _SECRET_REF_RE.fullmatch(value.strip())
        if match:
            names.add(match.group(1))
    return names


def _load_effective_config() -> tuple[dict[str, Any], Path, bool]:
    target = configured_path()
    if target.is_file():
        return load_config(target), target, False
    if _DEFAULT_PROFILE_PATH.is_file():
        return load_config(_DEFAULT_PROFILE_PATH), target, True
    return empty_config(), target, True


def read_parser_center() -> dict[str, Any]:
    config, target, using_default = _load_effective_config()
    secret_names = sorted(_walk_secret_names(config))
    return {
        "ok": True,
        "schema": CONFIG_SCHEMA,
        "path": str(target),
        "exists": target.is_file(),
        "using_default": using_default,
        "config": redact(config),
        "secrets": [
            {"name": name, "configured": bool(str(os.getenv(name) or "").strip())}
            for name in secret_names
        ],
        "public_output_policy": {
            "provider_identity_visible": False,
            "third_party_domain_visible": False,
            "secrets_visible": False,
        },
    }


def save_parser_center(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    normalized = validate_config(config)
    result = atomic_write_config(normalized)
    return {
        **result,
        "message": "解析中心配置已保存。已启用 Provider 会在下次服务启动时接管对应功能；测试接口立即使用新配置。",
        "restart_required": True,
    }


def _resolve_test_provider(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), Mapping) else {}
    supplied = payload.get("provider")
    if isinstance(supplied, Mapping):
        return copy.deepcopy(dict(supplied)), dict(parameters)
    feature = str(payload.get("feature") or "").strip()
    provider_id = str(payload.get("provider_id") or "").strip()
    if not feature or not provider_id:
        raise ParserConfigError("测试请求需要 provider，或同时提供 feature 与 provider_id")
    config, _target, _using_default = _load_effective_config()
    return find_provider(config, feature, provider_id), dict(parameters)


def run_parser_center_test(payload: Mapping[str, Any]) -> dict[str, Any]:
    provider, parameters = _resolve_test_provider(payload)
    result = test_provider(provider, parameters)
    result["provider_id"] = str(provider.get("id") or "")
    result["public_output_policy"] = {
        "contains_provider_identity": False,
        "contains_third_party_domain": False,
    }
    return result


def validate_parser_center(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    normalized = validate_config(config)
    return {
        "ok": True,
        "message": "配置结构与公开输出策略校验通过",
        "config": redact(normalized),
    }


def install_parser_center_routes(app: FastAPI) -> None:
    @app.get("/parser-center", response_class=HTMLResponse)
    async def parser_center_page() -> str:
        return render_parser_center_page()

    @app.get("/admin/parser-center")
    async def admin_parser_center() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(read_parser_center)
        except ParserCenterError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/admin/parser-center/validate")
    async def admin_parser_center_validate(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(validate_parser_center, payload)
        except ParserCenterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/admin/parser-center/test")
    async def admin_parser_center_test(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(run_parser_center_test, payload)
        except ParserConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ParserCenterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"第三方测试失败：{type(exc).__name__}") from exc

    @app.post("/admin/parser-center")
    async def admin_parser_center_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_parser_center, payload)
        except ParserCenterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"解析中心配置写入失败：{exc}") from exc
