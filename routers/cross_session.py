import logging
import threading
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from so1_client import So1ClientError
from services.main_control_security import require_control_access

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")
_cooldown_lock = threading.Lock()
_last_started_at = 0.0
_COOLDOWN_SECONDS = 30.0


@router.post("/cross_session_init")
async def cross_session_init(
    request: Request,
    wait_seconds: int = Query(180, ge=10, le=600),
):
    global _last_started_at
    try:
        require_control_access(request)
    except Exception as exc:
        return JSONResponse(
            status_code=int(getattr(exc, "status_code", 403) or 403),
            content={"error": str(getattr(exc, "detail", "") or "管理员凭据无效")},
        )
    ctx = getattr(request.app.state, "ctx", None)
    client = getattr(ctx, "so1_client", None) or getattr(request.app.state, "so1_client", None)
    if client is None:
        return JSONResponse(status_code=503, content={"error": "so1客户端不可用"})
    now = time.monotonic()
    with _cooldown_lock:
        remaining = _COOLDOWN_SECONDS - (now - _last_started_at)
        if remaining > 0:
            return JSONResponse(
                status_code=429,
                content={"error": "人工登录启动过于频繁", "retry_after_seconds": int(remaining) + 1},
            )
        _last_started_at = now
    try:
        await client.bootstrap_manual_login(wait_seconds=wait_seconds)
        return {"status": "ok", "message": "so1会话初始化完成"}
    except So1ClientError as exc:
        logger.error("so1会话初始化失败: %s", exc)
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("so1会话初始化异常")
        return JSONResponse(status_code=500, content={"error": "会话初始化失败"})
