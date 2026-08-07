from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.main_control_security import require_control_access
from services.target_file_watch_service import (
    TargetFileWatchError,
    target_file_watch_service,
)


router = APIRouter(prefix="/api/v1/target-file-watch", tags=["target-file-watch"])


def _require(request: Request) -> None:
    require_control_access(request)


@router.get("/status")
async def target_file_watch_status(request: Request) -> dict[str, Any]:
    _require(request)
    return target_file_watch_service.status()


@router.get("/config")
async def target_file_watch_config(request: Request) -> dict[str, Any]:
    _require(request)
    return {"ok": True, "config": target_file_watch_service.sanitized_config()}


@router.put("/config")
async def target_file_watch_save_config(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    _require(request)
    try:
        return target_file_watch_service.save_config(body)
    except TargetFileWatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/check")
async def target_file_watch_check(request: Request) -> dict[str, Any]:
    _require(request)
    try:
        return await target_file_watch_service.check_once()
    except TargetFileWatchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"定向文件检查失败：{type(exc).__name__}") from exc


@router.post("/rebaseline")
async def target_file_watch_rebaseline(request: Request) -> dict[str, Any]:
    _require(request)
    return target_file_watch_service.rebaseline()
