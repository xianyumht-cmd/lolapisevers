from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from .admin_api import build_admin_overview, read_lanzou_config_file, update_lanzou_config_file
from .config import AppConfig, load_config, sanitized_config
from .monitor import LanzouMonitorService
from .ui import render_dashboard_page


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = config or load_config()
    service = LanzouMonitorService(app_config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="Lanzou Update Push API Server",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = app_config
    app.state.service = service

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return render_dashboard_page()

    @app.get("/ui", response_class=HTMLResponse)
    async def dashboard_alias() -> str:
        return render_dashboard_page()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return service.status()

    @app.get("/config")
    async def get_config() -> dict[str, Any]:
        return {"ok": True, "config": sanitized_config(app.state.config)}

    @app.get("/admin/overview")
    async def admin_overview() -> dict[str, Any]:
        return build_admin_overview(app.state.config, service.status())

    @app.get("/admin/lanzou-config")
    async def admin_lanzou_config() -> dict[str, Any]:
        return {"ok": True, "config": read_lanzou_config_file()}

    @app.post("/admin/lanzou-config")
    async def admin_save_lanzou_config(patch: dict[str, Any]) -> dict[str, Any]:
        next_config = update_lanzou_config_file(patch)
        service.reload_config(next_config)
        app.state.config = next_config
        return {
            "ok": True,
            "message": "蓝奏监控配置已保存并刷新运行时配置。",
            "config": sanitized_config(next_config),
        }

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

    return app
