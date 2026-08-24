from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from services.image_asset_store import get_image_asset_sync_manager

from . import management, parser_center_admin
from .config import sanitized_config
from .control_navigation import apply_control_navigation, select_parser_center_section
from .control_ui import (
    ASSET_DIRECTORY,
    render_debugger_page,
    render_diagnostics_page,
    render_lanzou_config_page,
    render_logs_page,
    render_main_config_page,
    render_overview_page,
    render_system_page,
    render_target_file_watch_page,
    render_targets_page,
    render_watchers_page,
)
from .image_cache_ui import render_image_cache_page
from .lolban_console import install_lolban_console_routes
from .lolban_presets import ensure_lolban_provider_presets
from .maintenance import (
    list_config_backups,
    read_audit,
    rollback_config,
)
from .parser_center_retry_admin import install_parser_center_retry_routes
from .parser_center_ui_guard import render_parser_center_page as render_guarded_parser_center_page
from .release_update_guard import (
    ReleaseUpdateError,
    pause_release_update,
    reconnect_release_update,
    release_update_status,
    reset_release_update,
    resume_release_update,
    start_release_update,
)
from .release_updater import save_release_token
from .security import security_status
from .service_restart_controller import (
    schedule_windows_service_restart,
    windows_service_status,
)
from .state_recovery import recover_state_file
from .target_file_watch_admin import (
    TargetFileWatchAdminError,
    check_target_file_watch_now,
    read_target_file_watch_overview,
    rebaseline_target_file_watch,
)


_NEW_CONTROL_PATHS = {"/", "/ui"}
_MIGRATED_TAB_REDIRECTS = {
    "overview": "/",
    "mainconfig": "/main-config",
    "lanzouconfig": "/lanzou/config",
    "watchers": "/lanzou/watchers",
    "targets": "/lanzou/targets",
    "debugger": "/api-debugger",
    "logs": "/logs",
    "diagnostics": "/diagnostics",
    "system": "/system",
}
_CONTROL_PAGE_ACTIVE = {
    "/parser-center": "parser-center",
    "/parser-center/secrets": "parser-secrets",
    "/parser-center/advanced": "parser-center",
    "/query-console/lolban": "lolban",
}


def _decorate_control_page(path: str, page: str) -> str:
    active = _CONTROL_PAGE_ACTIVE.get(path)
    if active is None:
        return page
    return apply_control_navigation(page, active=active)


def _uses_new_overview(request: Request) -> bool:
    return request.url.path in _NEW_CONTROL_PATHS and not request.query_params.get("tab")


def _migrated_tab_target(request: Request) -> str | None:
    if request.url.path not in _NEW_CONTROL_PATHS:
        return None
    return _MIGRATED_TAB_REDIRECTS.get(str(request.query_params.get("tab") or "").strip().lower())


async def _read_response_body(response) -> bytes:
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk))
    return b"".join(chunks)


def _response_headers(response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-encoding"}
    }


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

    app.mount(
        "/control-assets",
        StaticFiles(directory=str(ASSET_DIRECTORY), check_dir=True),
        name="control-assets",
    )

    @app.get("/main-config", response_class=HTMLResponse, include_in_schema=False)
    async def main_config_page() -> str:
        return render_main_config_page()

    @app.get("/lanzou/config", response_class=HTMLResponse, include_in_schema=False)
    async def lanzou_config_page() -> str:
        return render_lanzou_config_page()

    @app.get("/lanzou/watchers", response_class=HTMLResponse, include_in_schema=False)
    async def lanzou_watchers_page() -> str:
        return render_watchers_page()

    @app.get("/lanzou/targets", response_class=HTMLResponse, include_in_schema=False)
    async def lanzou_targets_page() -> str:
        return render_targets_page()

    @app.get("/target-file-watch", response_class=HTMLResponse, include_in_schema=False)
    async def target_file_watch_page() -> str:
        return render_target_file_watch_page()

    @app.get("/api-debugger", response_class=HTMLResponse, include_in_schema=False)
    async def api_debugger_page() -> str:
        return render_debugger_page()

    @app.get("/logs", response_class=HTMLResponse, include_in_schema=False)
    async def logs_page() -> str:
        return render_logs_page()

    @app.get("/diagnostics", response_class=HTMLResponse, include_in_schema=False)
    async def diagnostics_page() -> str:
        return render_diagnostics_page()

    @app.get("/system", response_class=HTMLResponse, include_in_schema=False)
    async def system_page() -> str:
        return render_system_page()

    parser_center_admin.render_parser_center_page = render_guarded_parser_center_page
    parser_center_admin.install_parser_center_routes(app)

    @app.get("/parser-center/secrets", response_class=HTMLResponse, include_in_schema=False)
    async def parser_center_secrets_page() -> str:
        return select_parser_center_section(render_guarded_parser_center_page(), "backups")

    @app.get("/parser-center/advanced", response_class=HTMLResponse, include_in_schema=False)
    async def parser_center_advanced_page() -> str:
        return select_parser_center_section(render_guarded_parser_center_page(), "advanced")

    install_parser_center_retry_routes(app)
    install_lolban_console_routes(app)

    @app.middleware("http")
    async def professional_control_panel(request: Request, call_next):
        migrated_target = _migrated_tab_target(request)
        if migrated_target:
            return RedirectResponse(url=migrated_target, status_code=307)

        response = await call_next(request)
        content_type = str(response.headers.get("content-type") or "").lower()
        if "text/html" not in content_type:
            return response

        if _uses_new_overview(request):
            return HTMLResponse(
                render_overview_page(),
                status_code=response.status_code,
                headers=_response_headers(response),
            )

        active = _CONTROL_PAGE_ACTIVE.get(request.url.path)
        if active is None:
            return response

        raw = await _read_response_body(response)
        try:
            page = raw.decode("utf-8")
        except UnicodeDecodeError:
            return Response(
                raw,
                status_code=response.status_code,
                headers=_response_headers(response),
            )
        decorated = _decorate_control_page(request.url.path, page)
        return HTMLResponse(
            decorated,
            status_code=response.status_code,
            headers=_response_headers(response),
        )

    @app.get("/security/status")
    async def get_security_status() -> dict[str, object]:
        return security_status()

    @app.get("/admin/target-file-watch")
    async def admin_target_file_watch() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                read_target_file_watch_overview,
                app.state.main_base_url,
            )
        except TargetFileWatchAdminError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/admin/target-file-watch/check")
    async def admin_target_file_watch_check() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                check_target_file_watch_now,
                app.state.main_base_url,
            )
        except TargetFileWatchAdminError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/admin/target-file-watch/rebaseline")
    async def admin_target_file_watch_rebaseline() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                rebaseline_target_file_watch,
                app.state.main_base_url,
            )
        except TargetFileWatchAdminError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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

    @app.get("/admin/update/status")
    async def admin_update_status() -> dict[str, Any]:
        return await asyncio.to_thread(release_update_status)

    @app.post("/admin/update/token")
    async def admin_update_token(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = str((payload or {}).get("token") or "")
        try:
            return await asyncio.to_thread(save_release_token, token)
        except OSError as exc:
            return {"ok": False, "error": f"Token 保存失败：{exc.__class__.__name__}"}

    @app.post("/admin/update/start")
    async def admin_update_start() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(start_release_update)
        except ReleaseUpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"一键升级启动失败：{exc.__class__.__name__}") from exc

    @app.post("/admin/update/pause")
    async def admin_update_pause() -> dict[str, Any]:
        return await asyncio.to_thread(pause_release_update)

    @app.post("/admin/update/resume")
    async def admin_update_resume() -> dict[str, Any]:
        return await asyncio.to_thread(resume_release_update)

    @app.post("/admin/update/reconnect")
    async def admin_update_reconnect() -> dict[str, Any]:
        return await asyncio.to_thread(reconnect_release_update)

    @app.post("/admin/update/reset")
    async def admin_update_reset() -> dict[str, Any]:
        return await asyncio.to_thread(reset_release_update)
