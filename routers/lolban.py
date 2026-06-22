import logging
from typing import Any, Dict

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from services.lolban_service import format_lolban_text, get_lolban_result, valid_qq

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")


def _error(message: str, output: str, status_code: int = 400) -> Response:
    if output == "json":
        return JSONResponse(status_code=status_code, content={"code": status_code, "msg": message, "data": {}})
    return PlainTextResponse(message, status_code=status_code, media_type="text/plain; charset=utf-8")


def _response(payload: Dict[str, Any], output: str) -> Response:
    if output == "json":
        return JSONResponse(content=payload)
    return PlainTextResponse(format_lolban_text(payload), media_type="text/plain; charset=utf-8")


@router.get("/api/v2/lolban")
@router.get("/lolban")
async def lolban(qq: str = Query(..., description="QQ号码"), output: str = Query("text", description="text or json")):
    qq = str(qq or "").strip()
    output = (output or "text").strip().lower()
    if output not in {"text", "json"}:
        output = "text"
    if not valid_qq(qq):
        return _error("请输入有效的QQ号（5-11位数字）", output, 400)
    try:
        payload, source, _ = await get_lolban_result(qq)
        logger.info("lolban query qq=%s status=%s source=%s", qq, payload.get("data", {}).get("status"), source)
        return _response(payload, output)
    except Exception as exc:
        logger.warning("lolban query failed qq=%s error=%s", qq, exc)
        return _error("查询失败：接口繁忙，请稍后再试", output, 503)
