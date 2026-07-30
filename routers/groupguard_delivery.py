from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from renderers.cross_image import build_cross_image_response
from renderers.shard_image import build_shard_image_response
from routers.aram_augments import _build_cached_image_response
from services.aram_augments_service import query_aram_augments
from services.battle_delivery import battle_meta, format_battle_text
from services.contact_risk_service import (
    contact_risk_meta,
    format_contact_risk_report_text,
    format_contact_risk_text,
    query_contact_risk,
    report_contact_risk,
)
from services.cross_query_service import query_cross
from services.dynamic_query_service import dynamic_meta, format_dynamic_text, query_dynamic
from services.lolban_service import format_lolban_text, get_lolban_result, valid_qq
from services.query_delivery import (
    choose_text_delivery,
    error_envelope,
    format_aram_text,
    format_shard_text,
    image_delivery,
    normalize_capabilities,
    normalize_preferred,
    request_id,
    safe_client_request_id,
    safe_meta,
    success_envelope,
)
from services.shard_service import query_shard


router = APIRouter()
logger = logging.getLogger("LOLDataSystem")

_FEATURE_ALIASES = {
    "shard": "shard",
    "shard_query": "shard",
    "合集": "shard",
    "aram": "aram",
    "aram_augments": "aram",
    "海符榜": "aram",
    "lolban": "lolban",
    "ban": "lolban",
    "查封号": "lolban",
    "battle": "battle",
    "cross": "battle",
    "cross_query": "battle",
    "查战绩": "battle",
    "scammer": "scammer",
    "scammer_query": "scammer",
    "查骗子": "scammer",
    "peer": "peer",
    "peer_query": "peer",
    "查同行": "peer",
    "dynamic": "dynamic",
    "dynamic_query": "dynamic",
}
_REPORT_FEATURE_ALIASES = {
    "scammer_report": "scammer_report",
    "举报骗子": "scammer_report",
    "peer_report": "peer_report",
    "举报同行": "peer_report",
}
_IMAGE_FEATURES = {"shard", "aram", "battle"}


def _canonical_feature(value: Any) -> str:
    return _FEATURE_ALIASES.get(str(value or "").strip().lower(), "")


def _canonical_report_feature(value: Any) -> str:
    return _REPORT_FEATURE_ALIASES.get(str(value or "").strip().lower(), "")


def _error_code(status_code: int) -> tuple[str, bool, int]:
    if status_code == 400:
        return "invalid_query", False, 0
    if status_code == 404:
        return "not_found", False, 0
    if status_code == 409:
        return "conflict", False, 0
    if status_code in {408, 429}:
        return "temporarily_unavailable", True, 15
    if status_code >= 500:
        return "temporarily_unavailable", True, 30
    return "request_failed", False, 0


def _json_error(
    *,
    feature: str,
    status_code: int,
    message: str,
    client_request_id: str,
    server_request_id: str,
) -> JSONResponse:
    code, retryable, retry_after = _error_code(status_code)
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(
            feature=feature or "unknown",
            code=code,
            user_message=message,
            retryable=retryable,
            retry_after_seconds=retry_after,
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        ),
    )


def _image_response_ok(response: Response) -> bool:
    return (
        int(getattr(response, "status_code", 500) or 500) < 400
        and str(getattr(response, "media_type", "") or "").lower().startswith("image/")
        and bool(getattr(response, "body", b""))
    )


def _filename(feature: str, payload: Mapping[str, Any]) -> str:
    hero = payload.get("hero") if isinstance(payload.get("hero"), Mapping) else {}
    identity = str(
        hero.get("alias")
        or hero.get("name")
        or payload.get("name")
        or "result"
    ).strip()
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in identity).strip("-")
    return f"{feature}-{safe or 'result'}.png"


async def _render_feature_image(request: Request, feature: str, payload: Dict[str, Any]) -> Response:
    ctx = getattr(request.app.state, "ctx", None)
    if feature == "shard":
        return await asyncio.to_thread(build_shard_image_response, ctx, payload)
    if feature == "battle":
        return await asyncio.to_thread(build_cross_image_response, ctx, payload)
    return await asyncio.to_thread(
        _build_cached_image_response,
        ctx,
        payload,
        request.headers.get("if-none-match", ""),
    )


def _delivery_for_text(text: str, capabilities: Mapping[str, bool], preferred: str):
    delivery = choose_text_delivery(text, capabilities, preferred)
    if delivery is None:
        raise ValueError("客户端未声明可用的文本或转发能力")
    return delivery


def _meta_for_feature(feature: str, payload: Mapping[str, Any], *, delivery_fallback: str = ""):
    if feature == "battle":
        return battle_meta(payload, delivery_fallback=delivery_fallback)
    if feature in {"scammer", "peer"}:
        return contact_risk_meta(payload)
    if feature == "dynamic":
        return dynamic_meta(payload)
    return safe_meta(payload, delivery_fallback=delivery_fallback)


def _identifier_parameters(parameters: Mapping[str, Any]) -> tuple[str, str]:
    identifier_type = str(parameters.get("identifier_type") or parameters.get("type") or "").strip()
    if not identifier_type:
        identifier_type = "wechat" if parameters.get("wechat") or parameters.get("wx") else "qq"
    identifier = str(
        parameters.get("identifier")
        or parameters.get("account")
        or parameters.get("qq")
        or parameters.get("wechat")
        or parameters.get("wx")
        or ""
    ).strip()
    return identifier_type, identifier


@router.post("/api/v1/groupguard/query")
async def groupguard_query(request: Request, body: Dict[str, Any]):
    server_request_id = request_id()
    body = body if isinstance(body, dict) else {}
    client_request_id = safe_client_request_id(body.get("request_id"))
    feature = _canonical_feature(body.get("feature"))
    parameters = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
    capabilities = normalize_capabilities(body.get("capabilities"))
    preferred = normalize_preferred(body.get("preferred"))

    if not feature:
        return _json_error(
            feature="unknown",
            status_code=400,
            message="不支持的查询功能",
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )

    ctx = getattr(request.app.state, "ctx", None)
    if feature in {"shard", "aram", "battle", "scammer", "peer", "dynamic"} and ctx is None:
        return _json_error(
            feature=feature,
            status_code=503,
            message="查询服务暂不可用，请稍后再试",
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )

    try:
        if feature == "lolban":
            qq = str(parameters.get("qq") or "").strip()
            if not valid_qq(qq):
                return _json_error(
                    feature=feature,
                    status_code=400,
                    message="请输入有效的QQ号（5-11位数字）",
                    client_request_id=client_request_id,
                    server_request_id=server_request_id,
                )
            payload, _source, _ttl = await get_lolban_result(qq)
            text = format_lolban_text(payload)
            delivery = _delivery_for_text(text, capabilities, preferred)
            return JSONResponse(
                content=success_envelope(
                    feature=feature,
                    delivery=delivery,
                    meta=safe_meta(payload),
                    client_request_id=client_request_id,
                    server_request_id=server_request_id,
                )
            )

        if feature == "dynamic":
            command_id = str(parameters.get("command_id") or "").strip()
            payload = await query_dynamic(ctx, command_id, parameters)
            text = format_dynamic_text(payload)
        elif feature in {"scammer", "peer"}:
            identifier_type, identifier = _identifier_parameters(parameters)
            payload = await query_contact_risk(ctx, feature, identifier_type, identifier)
            text = format_contact_risk_text(payload)
        elif feature == "battle":
            name = str(parameters.get("name") or parameters.get("player_id") or "").strip()
            region = str(parameters.get("region") or "").strip() or None
            if not name:
                return _json_error(
                    feature=feature,
                    status_code=400,
                    message="请输入玩家ID，例如：张三#12345",
                    client_request_id=client_request_id,
                    server_request_id=server_request_id,
                )
            payload = await query_cross(ctx, name=name, region=region, output_format="pretty")
            text = format_battle_text(payload)
        else:
            hero = str(parameters.get("hero") or "").strip()
            if not hero:
                return _json_error(
                    feature=feature,
                    status_code=400,
                    message="请输入英雄中文名、称号或英文名",
                    client_request_id=client_request_id,
                    server_request_id=server_request_id,
                )
            if feature == "shard":
                payload = await query_shard(ctx, hero=hero)
                text = format_shard_text(payload)
            else:
                payload = await query_aram_augments(ctx, hero=hero)
                text = format_aram_text(payload)

        wants_image = (
            feature in _IMAGE_FEATURES
            and preferred in {"auto", "image"}
            and capabilities.get("image", False)
        )
        fallback_reason = ""
        if preferred == "image" and feature not in _IMAGE_FEATURES:
            fallback_reason = "image_not_supported"
        if wants_image:
            rendered = await _render_feature_image(request, feature, payload)
            if _image_response_ok(rendered):
                delivery = image_delivery(
                    bytes(rendered.body),
                    mime_type=str(rendered.media_type or "image/png"),
                    filename=_filename(feature, payload),
                )
                return JSONResponse(
                    content=success_envelope(
                        feature=feature,
                        delivery=delivery,
                        meta=_meta_for_feature(feature, payload),
                        client_request_id=client_request_id,
                        server_request_id=server_request_id,
                    )
                )
            fallback_reason = "image_render_failed"

        delivery = _delivery_for_text(text, capabilities, preferred if preferred != "image" else "auto")
        return JSONResponse(
            content=success_envelope(
                feature=feature,
                delivery=delivery,
                meta=_meta_for_feature(feature, payload, delivery_fallback=fallback_reason),
                client_request_id=client_request_id,
                server_request_id=server_request_id,
            )
        )
    except ValueError as exc:
        return _json_error(
            feature=feature,
            status_code=406,
            message=str(exc),
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )
    except Exception as exc:
        status_code = int(getattr(exc, "status_code", 503) or 503)
        detail = str(getattr(exc, "detail", "") or "")
        if status_code >= 500:
            logger.exception(
                "groupguard delivery failed feature=%s request_id=%s",
                feature,
                server_request_id,
            )
            detail = "查询服务暂不可用，请稍后再试"
        elif not detail:
            detail = "查询失败，请检查参数"
        return _json_error(
            feature=feature,
            status_code=status_code,
            message=detail,
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )


@router.post("/api/v1/groupguard/report")
async def groupguard_report(request: Request, body: Dict[str, Any]):
    server_request_id = request_id()
    body = body if isinstance(body, dict) else {}
    client_request_id = safe_client_request_id(body.get("request_id"))
    feature = _canonical_report_feature(body.get("feature"))
    parameters = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
    capabilities = normalize_capabilities(body.get("capabilities"))
    preferred = normalize_preferred(body.get("preferred"))

    if not feature:
        return _json_error(
            feature="unknown",
            status_code=400,
            message="不支持的举报功能",
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )
    if not client_request_id:
        return _json_error(
            feature=feature,
            status_code=400,
            message="举报请求必须提供 request_id",
            client_request_id="",
            server_request_id=server_request_id,
        )
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return _json_error(
            feature=feature,
            status_code=503,
            message="举报服务暂不可用，请稍后再试",
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )

    try:
        identifier_type, identifier = _identifier_parameters(parameters)
        category = "peer" if feature == "peer_report" else "scammer"
        payload = await report_contact_risk(
            ctx,
            request_id=client_request_id,
            category=category,
            identifier_type=identifier_type,
            identifier_value=identifier,
            content=str(parameters.get("content") or parameters.get("evidence") or ""),
            source=str(body.get("client") or parameters.get("source") or "channel-client"),
            actor_id=str(parameters.get("actor_id") or ""),
            group_id=str(parameters.get("group_id") or ""),
        )
        text = format_contact_risk_report_text(payload)
        delivery = _delivery_for_text(text, capabilities, preferred if preferred != "image" else "auto")
        record = payload.get("record") if isinstance(payload.get("record"), Mapping) else {}
        meta = {
            "category": category,
            "identifier_type": str(payload.get("identifier_type") or ""),
            "identifier_value": str(payload.get("identifier_value") or ""),
            "duplicate": bool(payload.get("duplicate")),
            "report_count": int(record.get("report_count") or 0),
        }
        return JSONResponse(
            content=success_envelope(
                feature=feature,
                delivery=delivery,
                meta=meta,
                client_request_id=client_request_id,
                server_request_id=server_request_id,
            )
        )
    except ValueError as exc:
        return _json_error(
            feature=feature,
            status_code=406,
            message=str(exc),
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )
    except Exception as exc:
        status_code = int(getattr(exc, "status_code", 503) or 503)
        detail = str(getattr(exc, "detail", "") or "")
        if status_code >= 500:
            logger.exception(
                "groupguard report failed feature=%s request_id=%s",
                feature,
                server_request_id,
            )
            detail = "举报服务暂不可用，请稍后再试"
        elif not detail:
            detail = "举报失败，请检查参数"
        return _json_error(
            feature=feature,
            status_code=status_code,
            message=detail,
            client_request_id=client_request_id,
            server_request_id=server_request_id,
        )
