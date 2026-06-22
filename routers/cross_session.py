import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from so1_client import So1ClientError

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")


@router.post("/cross_session_init")
async def cross_session_init(request: Request, wait_seconds: int = Query(180)):
    ctx = getattr(request.app.state, "ctx", None)
    client = getattr(ctx, "so1_client", None) or getattr(request.app.state, "so1_client", None)
    if client is None:
        return JSONResponse(status_code=503, content={"error": "so1客户端不可用"})
    try:
        await client.bootstrap_manual_login(wait_seconds=wait_seconds)
        return {"status": "ok", "message": "so1会话初始化完成"}
    except So1ClientError as exc:
        logger.error("so1会话初始化失败: %s", exc)
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("so1会话初始化异常")
        return JSONResponse(status_code=500, content={"error": f"会话初始化失败: {exc}"})
