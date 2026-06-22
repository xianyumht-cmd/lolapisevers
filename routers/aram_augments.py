import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from renderers.aram_augments_image import build_aram_augment_image_response
from services.aram_augments_service import query_aram_augments

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")


@router.get("/aram_augments")
async def aram_augments(
    request: Request,
    hero: str = Query(..., description="英雄中文名、称号或英文名"),
    output: str = Query("image", description="输出格式：image 或 json"),
):
    hero = hero.strip()
    output_format = output.strip().lower()
    if not hero:
        return JSONResponse(status_code=400, content={"error": "缺少参数 hero"})
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return JSONResponse(status_code=503, content={"error": "应用上下文不可用"})
    try:
        payload = await query_aram_augments(ctx, hero=hero)
        if output_format == "image":
            return build_aram_augment_image_response(ctx, payload)
        return payload
    except Exception as exc:
        status_code = getattr(exc, "status_code", 503)
        detail = getattr(exc, "detail", str(exc))
        if status_code >= 500:
            logger.exception("海符榜查询失败 hero=%s", hero)
        return JSONResponse(status_code=status_code, content={"error": detail})
