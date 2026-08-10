import asyncio
import hashlib
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from renderers.aram_balance_overlay import (
    build_aram_augment_image_with_balance as build_aram_augment_image_response,
)
from services.aram_augments_service import query_aram_augments
from services.aram_balance_service import query_aram_balance

router = APIRouter()
logger = logging.getLogger("LOLDataSystem")
ARAM_IMAGE_RENDERER_VERSION = "3"


def _balance_unavailable(error_class: str = "unexpected_error") -> dict:
    return {
        "status": "unavailable",
        "provider": "arammayhem",
        "patch": "",
        "changes": [],
        "summary": "",
        "stale": False,
        "snapshot_age_seconds": 0,
        "error_class": error_class,
    }


def _payload_with_balance(ctx, payload: dict) -> dict:
    if isinstance(payload.get("balance"), dict):
        return payload
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    hero_query = str(
        hero.get("alias")
        or hero.get("name")
        or hero.get("title")
        or payload.get("query")
        or ""
    ).strip()
    enriched = dict(payload)
    if not hero_query:
        enriched["balance"] = _balance_unavailable("hero_not_found")
        return enriched
    try:
        enriched["balance"] = query_aram_balance(ctx, hero_query)
    except Exception as exc:
        logger.warning(
            "海符榜图片英雄平衡查询降级 hero=%s error=%s",
            hero_query,
            exc.__class__.__name__,
        )
        enriched["balance"] = _balance_unavailable(exc.__class__.__name__)
    return enriched


def _aram_image_cache_key(payload: dict) -> tuple[str, str]:
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    canonical_alias = str(hero.get("alias") or hero.get("name") or "unknown").strip().casefold()
    projection = {
        "hero": hero,
        "rows": payload.get("rows") or [],
        "item_builds": payload.get("item_builds") or [],
        "starter_items": payload.get("starter_items") or [],
        "boots": payload.get("boots") or [],
        "summoner_spells": payload.get("summoner_spells") or [],
        "skill_order": payload.get("skill_order") or [],
        "balance": payload.get("balance") or {},
        "total": payload.get("total") or 0,
        "renderer": ARAM_IMAGE_RENDERER_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(projection, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"aram_image:{canonical_alias}:{digest}", f'"{digest}"'


def _image_response(body: bytes, etag: str, max_age: int, cache_status: str) -> Response:
    return Response(
        content=body,
        media_type="image/png",
        headers={
            "ETag": etag,
            "Cache-Control": f"public, max-age={max_age}",
            "X-Image-Bytes": str(len(body)),
            "X-Image-Cache": cache_status,
        },
    )


def _build_cached_image_response(ctx, payload: dict, if_none_match: str = "") -> Response:
    payload = _payload_with_balance(ctx, payload)
    cache_key, etag = _aram_image_cache_key(payload)
    max_age = int(getattr(ctx, "aram_image_cache_seconds", 300))
    if if_none_match.strip() == etag:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": f"public, max-age={max_age}", "X-Image-Cache": "not-modified"},
        )
    cached = ctx.aram_image_cache.get(cache_key)
    if isinstance(cached, bytes):
        return _image_response(cached, etag, max_age, "hit")

    lock = ctx.aram_image_lock(cache_key)
    with lock:
        cached = ctx.aram_image_cache.get(cache_key)
        if isinstance(cached, bytes):
            return _image_response(cached, etag, max_age, "hit")
        rendered = build_aram_augment_image_response(ctx, payload)
        if rendered.status_code >= 400 or not str(rendered.media_type or "").startswith("image/"):
            return rendered
        body = bytes(rendered.body)
        ctx.aram_image_cache.set(cache_key, body)
        return _image_response(body, etag, max_age, "miss")


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
        payload_result, balance_result = await asyncio.gather(
            query_aram_augments(ctx, hero=hero),
            asyncio.to_thread(query_aram_balance, ctx, hero),
            return_exceptions=True,
        )
        if isinstance(payload_result, BaseException):
            raise payload_result
        payload = dict(payload_result)
        if isinstance(balance_result, BaseException):
            logger.warning(
                "海符榜英雄平衡查询降级 hero=%s error=%s",
                hero,
                balance_result.__class__.__name__,
            )
            payload["balance"] = _balance_unavailable(balance_result.__class__.__name__)
        else:
            payload["balance"] = balance_result

        if output_format == "image":
            return await asyncio.to_thread(
                _build_cached_image_response,
                ctx,
                payload,
                request.headers.get("if-none-match", ""),
            )
        return payload
    except Exception as exc:
        status_code = getattr(exc, "status_code", 503)
        detail = getattr(exc, "detail", str(exc))
        if status_code >= 500:
            logger.exception("海符榜查询失败 hero=%s", hero)
        return JSONResponse(status_code=status_code, content={"error": detail})
