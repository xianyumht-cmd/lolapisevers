from __future__ import annotations

import asyncio
import copy
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
    test_provider,
    validate_config,
)

from . import management
from .parser_center_ui import render_parser_center_page


_SECRET_REF_RE = re.compile(r"^\$secret:([A-Za-z_][A-Za-z0-9_]*)$")
_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,95}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|cookie|api[_-]?key|access[_-]?key)",
    re.I,
)
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


def _redact_config(value: Any, *, key: str = "") -> Any:
    """Redact literal credentials while preserving declarative secret refs.

    The WebUI must receive ``$secret:NAME`` unchanged so a read/edit/save
    round trip cannot silently replace the reference with ``***``. Resolved
    or literal credentials under sensitive keys remain hidden.
    """

    if isinstance(value, str) and _SECRET_REF_RE.fullmatch(value.strip()):
        return value
    if _SENSITIVE_KEY_RE.search(str(key or "")):
        return "***"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_config(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_config(item) for item in value]
    return copy.deepcopy(value)


def _load_effective_config() -> tuple[dict[str, Any], Path, bool]:
    target = configured_path()
    if target.is_file():
        return load_config(target), target, False
    if _DEFAULT_PROFILE_PATH.is_file():
        return load_config(_DEFAULT_PROFILE_PATH), target, True
    return empty_config(), target, True


def _secret_configured(name: str) -> bool:
    if str(os.getenv(name) or "").strip():
        return True
    try:
        if management.APP_ENV_PATH.is_file():
            values = management._parse_env_values(
                management.APP_ENV_PATH.read_text(encoding="utf-8-sig")
            )
            value = str(values.get(name) or "").strip()
            return bool(value and value != "CHANGE_ME")
    except OSError:
        return False
    return False


def list_parser_backups() -> dict[str, Any]:
    target = configured_path()
    backups: list[dict[str, Any]] = []
    if target.parent.is_dir():
        for path in sorted(
            target.parent.glob(f"{target.name}.bak.*"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            stat = path.stat()
            backups.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at_epoch": int(stat.st_mtime),
                }
            )
    return {"ok": True, "path": str(target), "backups": backups[:100]}


def rollback_parser_center(payload: Mapping[str, Any]) -> dict[str, Any]:
    backup_name = Path(str(payload.get("backup_name") or "").strip()).name
    if not backup_name:
        raise ParserConfigError("backup_name is required")
    target = configured_path()
    allowed = {
        path.name: path
        for path in target.parent.glob(f"{target.name}.bak.*")
        if path.is_file()
    }
    backup = allowed.get(backup_name)
    if backup is None:
        raise ParserConfigError("指定的解析中心备份不存在")
    config = load_config(backup)
    result = atomic_write_config(config, target)
    result["config"] = _redact_config(config)
    return {
        **result,
        "restored_from": backup_name,
        "restart_required": True,
        "message": "解析中心配置已回滚；回滚前的当前配置也已自动备份。重启 LOLDataSystem 后生产查询生效。",
    }


def read_parser_center() -> dict[str, Any]:
    config, target, using_default = _load_effective_config()
    secret_names = sorted(_walk_secret_names(config))
    return {
        "ok": True,
        "schema": CONFIG_SCHEMA,
        "path": str(target),
        "exists": target.is_file(),
        "using_default": using_default,
        "config": _redact_config(config),
        "secrets": [
            {"name": name, "configured": _secret_configured(name)}
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
    result["config"] = _redact_config(normalized)
    return {
        **result,
        "message": "解析中心配置已保存。已启用 Provider 会在下次服务启动时接管对应功能；测试接口立即使用新配置。",
        "restart_required": True,
    }


def save_parser_secret(payload: Mapping[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip().upper()
    value = str(payload.get("value") or "")
    if not _SECRET_NAME_RE.fullmatch(name):
        raise ParserConfigError("Secret 名称必须是大写字母、数字和下划线")
    if not value.strip():
        raise ParserConfigError("Secret 值不能为空；空值不会用于清除已有密钥")
    config, _target, _using_default = _load_effective_config()
    referenced = _walk_secret_names(config)
    if name not in referenced:
        raise ParserConfigError("只能保存当前解析配置中已引用的 Secret")

    if name not in management._FIELD_BY_KEY:
        spec = {
            "key": name,
            "label": f"解析中心 Secret：{name}",
            "section": "接口与解析中心",
            "type": "secret",
        }
        management.MAIN_CONFIG_FIELDS.append(spec)
        management._FIELD_BY_KEY[name] = spec
    result = management.update_main_config({name: value})
    return {
        "ok": True,
        "name": name,
        "configured": True,
        "backup_path": str(result.get("backup_path") or ""),
        "restart_required": True,
        "message": "Secret 已安全写入本地环境配置；值未返回浏览器。重启 LOLDataSystem 后生产查询生效。",
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
        "config": _redact_config(normalized),
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

    @app.get("/admin/parser-center/backups")
    async def admin_parser_center_backups() -> dict[str, Any]:
        return await asyncio.to_thread(list_parser_backups)

    @app.post("/admin/parser-center/rollback")
    async def admin_parser_center_rollback(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(rollback_parser_center, payload)
        except ParserCenterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"解析中心配置回滚失败：{exc}") from exc

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

    @app.post("/admin/parser-center/secret")
    async def admin_parser_center_secret(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_parser_secret, payload)
        except ParserCenterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Secret 写入失败：{exc}") from exc

    @app.post("/admin/parser-center")
    async def admin_parser_center_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_parser_center, payload)
        except ParserCenterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"解析中心配置写入失败：{exc}") from exc
