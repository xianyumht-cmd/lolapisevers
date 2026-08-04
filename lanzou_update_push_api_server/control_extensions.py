from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response

from services.image_asset_store import get_image_asset_sync_manager

from . import management, parser_center_admin
from .config import sanitized_config
from .control_navigation import apply_control_navigation
from .image_cache_ui import render_image_cache_page
from .lolban_console import install_lolban_console_routes
from .lolban_presets import ensure_lolban_provider_presets
from .maintenance import (
    list_config_backups,
    read_audit,
    rollback_config,
    schedule_windows_service_restart,
    windows_service_status,
)
from .parser_center_retry_admin import install_parser_center_retry_routes
from .parser_center_ui_guard import render_parser_center_page as render_guarded_parser_center_page
from .security import security_status
from .state_recovery import recover_state_file


_CONTROL_PAGE_ACTIVE = {
    "/": "overview",
    "/ui": "overview",
    "/parser-center": "parser-center",
    "/query-console/lolban": "lolban",
}


def _decorate_control_page(path: str, page: str) -> str:
    active = _CONTROL_PAGE_ACTIVE.get(path)
    if active is None:
        return page
    return apply_control_navigation(page, active=active)


async def _read_response_body(response) -> bytes:
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk))
    return b"".join(chunks)


def _register_sensitive_lolban_fields() -> None:
    key = "LOL_BAN_UPSTREAM_URL"
    spec = management._FIELD_BY_KEY.get(key)
    if spec is None:
        spec = {
            "key": key,
            "label": "旧版封号上游 URL（请在封号查询配置页管理）",
            "section": "封号查询",
            "type": "secret",
        }
        management.MAIN_CONFIG_FIELDS.append(spec)
        management._FIELD_BY_KEY[key] = spec
        return
    spec["type"] = "secret"
    spec["label"] = "旧版封号上游 URL（请在封号查询配置页管理）"


def install_control_extensions(app: FastAPI, service) -> None:
    _register_sensitive_lolban_fields()
    try:
        app.state.lolban_preset_migration = ensure_lolban_provider_presets()
    except Exception as exc:
        app.state.lolban_preset_migration = {
            "ok": False,
            "changed": False,
            "error_class": type(exc).__name__,
        }
    parser_center_admin.render_parser_center_page = render_guarded_parser_center_page
    parser_center_admin.install_parser_center_routes(app)
    install_parser_center_retry_routes(app)
    install_lolban_console_routes(app)

    @app.middleware("http")
    async def professional_control_panel(request: Request, call_next):
        response = await call_next(request)
        active = _CONTROL_PAGE_ACTIVE.get(request.url.path)
        content_type = str(response.headers.get("content-type") or "").lower()
        if active is None or "text/html" not in content_type:
            return response
        raw = await _read_response_body(response)
        try:
            page = raw.decode("utf-8")
        except UnicodeDecodeError:
            headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
            return Response(raw, status_code=response.status_code, headers=headers)
        decorated = _decorate_control_page(request.url.path, page)
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-encoding"}
        }
        return HTMLResponse(
            decorated,
            status_code=response.status_code,
            headers=headers,
        )

    @app.get("/security/status")
    async def get_security_status() -> dict[str, object]:
        return security_status()

    @app.get("/image-cache", response_class=HTMLResponse)
    async def image_cache_page() -> str:
        return render_image_cache_page()

    @app.get("/admin/image-cache")
    async def admin_image_cache() -> dict[str, Any]:
        return await asyncio.to_thread(get_image_asset_sync_manager().status)

    @app.post("/admin/image-cache/sync")
    async def admin_image_cache_sync(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = str((payload or {}).get("mode") or "missing").strip().lower()
        try:
            return await asyncio.to_thread(get_image_asset_sync_manager().start, mode)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/admin/backups")
    async def admin_backups() -> dict[str, Any]:
        return await asyncio.to_thread(list_config_backups)

    @app.post("/admin/rollback/{kind}")
    async def admin_rollback(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        backup_name = str(payload.get("backup_name") or "").strip()
        if not backup_name:
            return {"ok": False, "error": "backup_name is required"}
        try:
            result = await asyncio.to_thread(rollback_config, kind, backup_name)
            if kind == "lanzou":
                next_config = result.pop("config")
                if service.store.path != next_config.state_path:
                    app.state.state_recovery = await asyncio.to_thread(
                        recover_state_file,
                        next_config.state_path,
                    )
                service.reload_config(next_config)
                app.state.config = next_config
                result["config"] = sanitized_config(next_config)
                result["state_recovery"] = app.state.state_recovery
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/admin/audit")
    async def admin_audit(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        return await asyncio.to_thread(read_audit, limit)

    @app.get("/admin/service/status")
    async def admin_service_status() -> dict[str, Any]:
        return await asyncio.to_thread(windows_service_status)

    @app.post("/admin/service/restart")
    async def admin_service_restart(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload or {}
        delay_seconds = int(data.get("delay_seconds") or 3)
        try:
            return await asyncio.to_thread(
                schedule_windows_service_restart,
                delay_seconds=delay_seconds,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
