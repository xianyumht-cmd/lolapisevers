import logging
from typing import Any, Dict

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from services.lolban_runtime import get_lolban_service
from services.lolban_service import apply_compat_payload, format_lolban_text, valid_qq

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")


def _error(message: str, output: str, status_code: int = 400) -> Response:
    if output == "json":
        return JSONResponse(status_code=status_code, content={"code": status_code, "msg": message, "data": {}})
    return PlainTextResponse(message, status_code=status_code, media_type="text/plain; charset=utf-8")


def _response(payload: Dict[str, Any], output: str, compat: str = "") -> Response:
    if output == "json":
        return JSONResponse(content=apply_compat_payload(payload, compat))
    return PlainTextResponse(format_lolban_text(payload), media_type="text/plain; charset=utf-8")


@router.get("/api/v2/lolban")
@router.get("/lolban")
async def lolban(
    qq: str = Query(..., description="QQ号码"),
    output: str = Query("text", description="text or json"),
    compat: str = Query("", description="optional compatibility mode, e.g. napcat"),
):
    qq = str(qq or "").strip()
    output = (output or "text").strip().lower()
    compat = str(compat or "").strip().lower()
    if output not in {"text", "json"}:
        output = "text"
    if not valid_qq(qq):
        return _error("请输入有效的QQ号（5-11位数字）", output, 400)
    try:
        payload, source, _ = await get_lolban_service().get_result(qq)
        logger.info("lolban query qq=%s status=%s source=%s compat=%s", qq, payload.get("data", {}).get("status"), source, compat)
        return _response(payload, output, compat)
    except Exception as exc:
        logger.warning("lolban query failed qq=%s error=%s", qq, exc)
        return _error("查询失败：接口繁忙，请稍后再试", output, 503)
