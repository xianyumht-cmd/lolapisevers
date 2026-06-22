import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from renderers.cross_image import build_cross_image_response
from renderers.cross_svg import build_cross_svg_response
from services.cross_query_service import query_cross

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")


@router.get("/cross_query")
async def cross_query(
    request: Request,
    name: str = Query(..., description="召唤师名称"),
    region: Optional[str] = Query(None, description="大区名称"),
    output: str = Query("pretty", description="输出格式：pretty 或 raw"),
):
    name = name.strip()
    region_str = region.strip() if region else None
    output_format = output.strip().lower()
    if not name:
        return JSONResponse(status_code=400, content={"error": "缺少参数 name"})

    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return JSONResponse(status_code=503, content={"error": "应用上下文不可用"})

    logger.info("收到跨区查询请求 name=%s region=%s", name, region_str or "")
    try:
        payload = await query_cross(ctx, name=name, region=region_str, output_format=output_format)
        if output_format == "image":
            return build_cross_image_response(payload)
        if output_format == "svg":
            return build_cross_svg_response(payload)
        return payload
    except Exception as exc:
        logger.exception("跨区查询失败 name=%s", name)
        return JSONResponse(status_code=503, content={"error": str(exc)})
