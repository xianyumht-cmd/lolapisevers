import logging
from typing import Any, Dict, List, Optional

from core.context import AppContext
from services.cross_formatter import build_cross_pretty
from services.cross_snapshot_service import get_cross_snapshot, upsert_cross_snapshot
from so1_client import So1ClientError

logger = logging.getLogger("LOLDataSystem")


def consume_cross_raw(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    basic = None
    rank = None
    history = None
    errors: List[Dict[str, Any]] = []
    for url, payload in raw_payload.items():
        data_obj = payload.get("data") if isinstance(payload, dict) else payload
        success = bool(payload.get("success")) if isinstance(payload, dict) else data_obj is not None
        if not success:
            err = payload.get("error") if isinstance(payload, dict) else None
            errors.append(
                {
                    "endpoint": url,
                    "code": (err or {}).get("errCode") if isinstance(err, dict) else None,
                    "message": (err or {}).get("message") if isinstance(err, dict) else "查询失败",
                    "trace": (err or {}).get("trace") if isinstance(err, dict) else None,
                    "request": payload.get("_request") if isinstance(payload, dict) else None,
                }
            )
        if "/customize-summoner-basic-by-name-region" in url and success:
            basic = data_obj
        elif "/origin-summoner-ranked-stats" in url and success:
            rank = data_obj
        elif "/customize-normal-match-history-simplified" in url and success:
            history = data_obj
    return {"basic": basic, "rank": rank, "history": history, "errors": errors}


async def query_cross(ctx: AppContext, *, name: str, region: Optional[str], output_format: str) -> Dict[str, Any]:
    region_str = region.strip() if region else None
    region_key = region_str or "AUTO"
    cache_key = f"cross:{name}:{region_key}:{output_format}"
    cache_hit, cache_ttl = ctx.cross_cache.get_with_remaining_ttl(cache_key)
    if isinstance(cache_hit, dict):
        cache_hit["source"] = "cache"
        cache_hit["cache_expires_in"] = cache_ttl
        return cache_hit

    db_instance = ctx.ensure_db()
    upstream_error = ""
    try:
        raw = await ctx.so1_client.query_summoner(name, region_name=region_str)
        parsed = consume_cross_raw(raw)
        basic = parsed["basic"]
        rank = parsed["rank"]
        history = parsed["history"]
        errors: List[Dict[str, Any]] = parsed["errors"]

        if basic is None and "#" in name:
            base_name = name.split("#", 1)[0].strip()
            if base_name:
                fallback_raw = await ctx.so1_client.query_summoner(base_name, region_name=region_str)
                parsed_fallback = consume_cross_raw(fallback_raw)
                basic = basic or parsed_fallback["basic"]
                rank = rank or parsed_fallback["rank"]
                history = history or parsed_fallback["history"]
                errors.extend(parsed_fallback["errors"])
                raw.update(fallback_raw)

        pretty_payload = build_cross_pretty(
            name=name,
            region=region_str or "",
            basic=basic,
            rank=rank,
            history=history,
            errors=errors,
            cache=ctx.cross_cache,
            logger=ctx.logger,
        )
        pretty_payload["source"] = "live"
        pretty_payload["is_stale"] = False
        pretty_payload["snapshot_updated_at"] = ""
        pretty_payload["cache_expires_in"] = ctx.config.cache_seconds
        raw_payload = {
            "name": name,
            "region": region_str or "",
            "basic": basic,
            "ranked": rank,
            "history": history,
            "raw_endpoint_count": len(raw),
            "errors": errors,
            "source": "live",
            "is_stale": False,
            "snapshot_updated_at": "",
            "cache_expires_in": ctx.config.cache_seconds,
        }
        response_payload = raw_payload if output_format == "raw" else pretty_payload
        ctx.cross_cache.set(cache_key, response_payload)
        if db_instance is not None:
            display_name = str((basic or {}).get("name") or (basic or {}).get("displayName") or name)
            await upsert_cross_snapshot(
                db_instance,
                query_name=name,
                region=region_key,
                display_name=display_name,
                payload_pretty=pretty_payload,
                payload_raw=raw_payload,
            )
        return response_payload
    except So1ClientError as exc:
        upstream_error = str(exc)
        logger.error("跨区查询失败: %s", exc)
    except Exception as exc:
        upstream_error = str(exc)
        logger.exception("跨区查询异常 name=%s", name)

    snapshot = await get_cross_snapshot(db_instance, query_name=name, region=region_key) if db_instance is not None else None
    if snapshot and bool(snapshot.get("is_success")):
        pretty_payload = snapshot.get("payload_pretty") if isinstance(snapshot.get("payload_pretty"), dict) else {}
        raw_payload = snapshot.get("payload_raw") if isinstance(snapshot.get("payload_raw"), dict) else None
        updated_at = snapshot.get("updated_at")
        updated_text = updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(updated_at, "strftime") else ""
        if not isinstance(pretty_payload, dict):
            pretty_payload = {}
        pretty_payload["source"] = "snapshot"
        pretty_payload["is_stale"] = True
        pretty_payload["snapshot_updated_at"] = updated_text
        pretty_payload["fallback_reason"] = upstream_error
        pretty_payload["cache_expires_in"] = ctx.config.cache_seconds
        if not isinstance(raw_payload, dict):
            raw_payload = {
                "name": snapshot.get("query_name") or name,
                "region": snapshot.get("region") or (region_str or ""),
                "source": "snapshot",
                "is_stale": True,
                "snapshot_updated_at": updated_text,
                "fallback_reason": upstream_error,
                "cache_expires_in": ctx.config.cache_seconds,
            }
        else:
            raw_payload["source"] = "snapshot"
            raw_payload["is_stale"] = True
            raw_payload["snapshot_updated_at"] = updated_text
            raw_payload["fallback_reason"] = upstream_error
            raw_payload["cache_expires_in"] = ctx.config.cache_seconds
        response_payload = raw_payload if output_format == "raw" else pretty_payload
        ctx.cross_cache.set(cache_key, response_payload)
        return response_payload

    raise RuntimeError(f"跨区查询失败: {upstream_error or '未知错误'}")
