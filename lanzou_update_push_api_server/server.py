from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .admin_api import build_admin_overview
from .api_debugger import fetch_openapi, invoke_api
from .config import AppConfig, sanitized_config
from .config_facade import lanzou_environment_overrides, read_main_config, update_main_config
from .control_extensions import install_control_extensions
from .log_facade import list_logs, read_log
from .management import (
    read_lanzou_config,
    repair_state,
    run_diagnostics,
    update_lanzou_config,
)
from .monitor import LanzouMonitorService
from .security import control_api_guard
from .state_recovery import recover_state_file
from .ui import render_dashboard_page
from .ui_runtime import render_runtime_dashboard


def _control_page() -> str:
    return render_runtime_dashboard()


def _fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=5, headers={"accept": "application/json"})
    try:
        data = response.json()
    except ValueError:
        data = {"ok": False, "status_code": response.status_code, "error": response.text[:2000]}
    if isinstance(data, dict):
        data.setdefault("ok", response.ok)
        return data
    return {"ok": response.ok, "status_code": response.status_code, "data": data}


def create_app(config: AppConfig | None = None) -> FastAPI:
    from .config import load_config

    app_config = config or load_config()
    state_recovery = recover_state_file(app_config.state_path)
    service = LanzouMonitorService(app_config)
    main_port = int(os.getenv("APP_PORT", "5001"))
    main_base_url = f"http://127.0.0.1:{main_port}"
    lanzou_base_url = f"http://127.0.0.1:{app_config.port}"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="Lanzou Update Push API Server",
        version="0.3.1",
        lifespan=lifespan,
    )
    app.middleware("http")(control_api_guard)
    app.state.config = app_config
    app.state.service = service
    app.state.state_recovery = state_recovery
    app.state.main_base_url = main_base_url
    app.state.lanzou_base_url = lanzou_base_url

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return _control_page()

    @app.get("/ui", response_class=HTMLResponse)
    async def dashboard_alias() -> str:
        return _control_page()

    @app.get("/legacy-ui", response_class=HTMLResponse)
    async def legacy_dashboard() -> str:
        return render_dashboard_page()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        status = service.status()
        status["state_recovery"] = app.state.state_recovery
        return status

    @app.get("/config")
    async def get_config() -> dict[str, Any]:
        return {"ok": True, "config": sanitized_config(app.state.config)}

    @app.get("/admin/overview")
    async def admin_overview() -> dict[str, Any]:
        status = service.status()
        status["state_recovery"] = app.state.state_recovery
        overview = build_admin_overview(app.state.config, status)
        overview["mainApi"]["baseUrl"] = app.state.main_base_url
        overview["mainApi"]["health"] = await asyncio.to_thread(
            _fetch_json,
            f"{app.state.main_base_url}/health",
        )
        overview["lanzou"]["baseUrl"] = app.state.lanzou_base_url
        overview["lanzou"]["environmentOverrides"] = lanzou_environment_overrides()
        return overview

    @app.get("/admin/main-config")
    async def admin_main_config() -> dict[str, Any]:
        return await asyncio.to_thread(read_main_config)

    @app.post("/admin/main-config")
    async def admin_save_main_config(patch: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(update_main_config, patch)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"主接口配置文件写入失败：{exc}") from exc

    @app.get("/admin/lanzou-config")
    async def admin_lanzou_config() -> dict[str, Any]:
        return {
            "ok": True,
            "config": await asyncio.to_thread(read_lanzou_config),
            "environment_overrides": lanzou_environment_overrides(),
        }

    @app.post("/admin/lanzou-config")
    async def admin_save_lanzou_config(patch: dict[str, Any]) -> dict[str, Any]:
        next_config, backup_path = await asyncio.to_thread(update_lanzou_config, patch)
        if service.store.path != next_config.state_path:
            app.state.state_recovery = await asyncio.to_thread(recover_state_file, next_config.state_path)
        service.reload_config(next_config)
        app.state.config = next_config
        return {
            "ok": True,
            "message": "蓝奏监控配置已保存并刷新运行时配置。监听地址或端口变化需要重启服务。",
            "config": sanitized_config(next_config),
            "backup_path": backup_path,
            "state_recovery": app.state.state_recovery,
            "environment_overrides": lanzou_environment_overrides(),
        }

    @app.get("/admin/openapi/{service_name}")
    async def admin_openapi(service_name: str) -> dict[str, Any]:
        if service_name == "lanzou":
            return {"ok": True, "service": service_name, "schema": app.openapi()}
        if service_name != "main":
            return {"ok": False, "error": "service must be main or lanzou"}
        try:
            schema = await asyncio.to_thread(fetch_openapi, app.state.main_base_url)
            return {"ok": True, "service": service_name, "schema": schema}
        except Exception as exc:
            return {"ok": False, "service": service_name, "error": str(exc)}

    @app.post("/admin/invoke")
    async def admin_invoke(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            service_name = str(payload.get("service") or "main")
            if service_name == "main":
                base_url = app.state.main_base_url
            elif service_name == "lanzou":
                base_url = app.state.lanzou_base_url
            else:
                raise ValueError("service must be main or lanzou")
            return await asyncio.to_thread(invoke_api, base_url, payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/admin/logs")
    async def admin_logs() -> dict[str, Any]:
        return await asyncio.to_thread(list_logs)

    @app.get("/admin/logs/{name}")
    async def admin_log(name: str, lines: int = Query(200, ge=1, le=5000), search: str = "") -> dict[str, Any]:
        try:
            return await asyncio.to_thread(read_log, name, lines, search)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/admin/diagnostics")
    async def admin_diagnostics() -> dict[str, Any]:
        return await asyncio.to_thread(run_diagnostics)

    @app.post("/admin/repair/state")
    async def admin_repair_state() -> dict[str, Any]:
        result = await asyncio.to_thread(repair_state)
        app.state.state_recovery = result
        return result

    @app.get("/watchers")
    async def watchers() -> dict[str, Any]:
        snapshots = service.store.data.get("snapshots", {})
        return {
            "ok": True,
            "watchers": [
                {
                    **watcher.__dict__,
                    "last_snapshot": snapshots.get(watcher.id, {}),
                }
                for watcher in app.state.config.watchers
            ],
        }

    @app.get("/events")
    async def events(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {"ok": True, "events": service.store.recent_events(limit)}

    @app.post("/scan")
    async def scan(watcher_id: str | None = None, notify: bool = True) -> dict[str, Any]:
        if watcher_id:
            return {"ok": True, "results": [await service.scan_watcher(watcher_id, notify=notify)]}
        return {"ok": True, "results": await service.scan_all(notify=notify)}

    @app.get("/files/{watcher_id}")
    async def files(watcher_id: str) -> dict[str, Any]:
        snapshot = service.store.data.get("snapshots", {}).get(watcher_id)
        if not snapshot:
            return {"ok": False, "error": "snapshot_not_found"}
        return {"ok": True, "snapshot": snapshot}

    @app.post("/notify/test")
    async def notify_test(watcher_id: str | None = None) -> dict[str, Any]:
        return await service.send_test_event(watcher_id)

    install_control_extensions(app, service)
    return app
