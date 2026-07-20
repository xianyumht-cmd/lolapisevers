from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Query

from .config import sanitized_config
from .maintenance import (
    list_config_backups,
    read_audit,
    rollback_config,
    schedule_windows_service_restart,
    windows_service_status,
)
from .security import security_status
from .state_recovery import recover_state_file


def install_control_extensions(app: FastAPI, service) -> None:
    @app.get("/security/status")
    async def get_security_status() -> dict[str, object]:
        return security_status()

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
