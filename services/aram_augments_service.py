from __future__ import annotations

import asyncio
import copy
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from core.context import AppContext
from services.aram_upstream_state import (
    load_aram_payload_snapshot,
    load_champion_catalog,
    record_aram_payload_error,
    request_opgg_html,
    safe_error_class,
    safe_error_message,
    save_aram_payload_snapshot,
)
from services.opgg_parser import (
    extract_opgg_augments,
    extract_opgg_core_builds,
    extract_opgg_item_rows,
    extract_opgg_skill_order,
    extract_opgg_summoner_spells,
)
from utils.text_utils import normalize_search_text


_payload_flights_lock = threading.Lock()
_payload_flights: Dict[Tuple[int, str], Future] = {}
_opgg_executor = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="aram-opgg",
)
_OPTIONAL_BUILD_KEYS = (
    "item_builds",
    "starter_items",
    "boots",
    "summoner_spells",
    "skill_order",
)


class AramRequiredUpstreamError(RuntimeError):
    def __init__(self, error_class: str, message: str, *, status: str = "failed"):
        super().__init__(message)
        self.error_class = str(error_class or "unavailable")
        self.status = str(status or "failed")


def get_champion_lookup_sources(ctx: AppContext) -> List[Dict[str, Any]]:
    # Preserve compatibility with existing tests and warm process caches created
    # before the persistent catalog envelope was introduced.
    cached = ctx.aram_augment_cache.get("champions")
    if isinstance(cached, list):
        return copy.deepcopy(cached)
    catalog = load_champion_catalog(ctx)
    champions = catalog.get("champions") if isinstance(catalog, dict) else []
    if not isinstance(champions, list):
        champions = []
    ctx.aram_augment_cache.set("champions", copy.deepcopy(champions))
    return copy.deepcopy(champions)


def _champion_lookup_meta(ctx: AppContext) -> Dict[str, Any]:
    catalog = ctx.aram_augment_cache.get("champion_catalog")
    if not isinstance(catalog, dict):
        return {
            "mode": "cache",
            "age_seconds": 0,
            "error_class": "",
            "snapshot_status": "",
        }
    return {
        "mode": str(catalog.get("mode") or "live"),
        "age_seconds": int(catalog.get("age_seconds") or 0),
        "error_class": str(catalog.get("error_class") or ""),
        "snapshot_status": str(catalog.get("snapshot_status") or ""),
    }


def find_champion_for_opgg(ctx: AppContext, query: str) -> Optional[Dict[str, Any]]:
    needle = normalize_search_text(query)
    if not needle:
        return None
    champions = get_champion_lookup_sources(ctx)
    for hero in champions:
        if needle in {
            normalize_search_text(hero.get("alias")),
            normalize_search_text(hero.get("slug")),
            normalize_search_text(hero.get("title")),
            normalize_search_text(hero.get("name")),
        }:
            return hero
    for hero in champions:
        haystack = normalize_search_text(
            ",".join(
                str(hero.get(key) or "")
                for key in ("alias", "slug", "title", "name", "keywords")
            )
        )
        if needle in haystack:
            return hero
    return None


def _slug_candidates(hero: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for value in [hero.get("slug"), hero.get("alias")]:
        slug = str(value or "").strip().lower()
        if slug and slug not in candidates:
            candidates.append(slug)
    if (
        str(hero.get("alias") or "").casefold() == "monkeyking"
        and "wukong" not in candidates
    ):
        candidates.insert(0, "wukong")
    return candidates


def _fetch_augment_rows(
    ctx: AppContext,
    slug_candidates: List[str],
) -> Dict[str, Any]:
    started = time.perf_counter()
    last_error_class = "unavailable"
    last_error_message = "未知错误"
    last_status = "failed"
    for slug in slug_candidates:
        url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/augments"
        response = request_opgg_html(
            ctx,
            page_kind="augments",
            slug=slug,
            url=url,
            attempts=2,
            connect_timeout=3.0,
            read_timeout=7.0,
        )
        if not response.ok:
            last_error_class = safe_error_class(response)
            last_error_message = safe_error_message(response) or last_error_class
            last_status = response.status
            continue
        try:
            rows = extract_opgg_augments(response.text)
        except Exception as exc:
            last_error_class = "parse_error"
            last_error_message = exc.__class__.__name__
            last_status = "failed"
            continue
        if rows:
            return {
                "rows": rows,
                "source_url": url,
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "attempts": response.attempts,
                "http_status": response.status_code,
                "source_id": response.source_id,
            }
        last_error_class = "validation_error"
        last_error_message = "页面中未找到强化符文数据"
        last_status = "failed"
    raise AramRequiredUpstreamError(
        last_error_class,
        last_error_message,
        status=last_status,
    )


def _empty_optional_build(
    *,
    status: str = "empty",
    error_class: str = "",
    duration_ms: float = 0.0,
) -> Dict[str, Any]:
    return {
        "item_builds": [],
        "starter_items": [],
        "boots": [],
        "summoner_spells": [],
        "skill_order": [],
        "status": status,
        "error_class": error_class,
        "duration_ms": duration_ms,
        "attempts": 0,
        "http_status": 0,
    }


def _fetch_optional_build(
    ctx: AppContext,
    slug_candidates: List[str],
) -> Dict[str, Any]:
    started = time.perf_counter()
    result = _empty_optional_build()
    for slug in slug_candidates:
        build_url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/build"
        response = request_opgg_html(
            ctx,
            page_kind="build",
            slug=slug,
            url=build_url,
            attempts=1,
            connect_timeout=2.0,
            read_timeout=4.5,
        )
        result["attempts"] = response.attempts
        result["http_status"] = response.status_code
        if not response.ok:
            result["status"] = "unavailable"
            result["error_class"] = safe_error_class(response)
            continue
        try:
            result["item_builds"] = extract_opgg_core_builds(response.text)
            result["starter_items"] = extract_opgg_item_rows(
                response.text,
                "starter_items",
                limit=2,
                max_items=3,
            )
            result["boots"] = extract_opgg_item_rows(
                response.text,
                "boots",
                limit=2,
                max_items=1,
            )
            result["summoner_spells"] = extract_opgg_summoner_spells(
                response.text
            )
            result["skill_order"] = extract_opgg_skill_order(response.text)
        except Exception as exc:
            result.update(
                _empty_optional_build(
                    status="unavailable",
                    error_class=f"parse_{exc.__class__.__name__}",
                )
            )
            continue
        if any(result[key] for key in _OPTIONAL_BUILD_KEYS):
            result["status"] = "ok"
            result["error_class"] = ""
            break
        result["status"] = "empty"
        result["error_class"] = "validation_error"
    result["duration_ms"] = round(
        (time.perf_counter() - started) * 1000,
        1,
    )
    return result


def _merge_optional_snapshot(
    build_result: Dict[str, Any],
    snapshot_payload: Any,
    snapshot_age_seconds: int,
) -> Dict[str, Any]:
    if build_result.get("status") == "ok" or not isinstance(snapshot_payload, dict):
        return build_result
    restored = False
    for key in _OPTIONAL_BUILD_KEYS:
        value = snapshot_payload.get(key)
        if isinstance(value, list) and value:
            build_result[key] = copy.deepcopy(value)
            restored = True
    if restored:
        build_result["status"] = "snapshot"
        build_result["snapshot_age_seconds"] = int(snapshot_age_seconds)
    return build_result


def _snapshot_fallback_payload(
    ctx: AppContext,
    *,
    query: str,
    snapshot: Any,
    error: AramRequiredUpstreamError,
    lookup_meta: Dict[str, Any],
    started: float,
) -> Dict[str, Any]:
    if not snapshot.ok or not isinstance(snapshot.payload, dict):
        raise HTTPException(
            status_code=503,
            detail=(
                "OP.GG 强化符文数据暂不可用"
                f"（{error.error_class}；本地快照状态：{snapshot.status}）"
            ),
        )
    result = copy.deepcopy(snapshot.payload)
    result["query"] = query
    result["source"] = (
        "snapshot" if error.status == "circuit_open" else "stale"
    )
    result["provider"] = "opgg"
    result["stale"] = True
    result["snapshot_age_seconds"] = int(snapshot.age_seconds)
    result["fallback_reason"] = f"opgg-aram-augments:{error.error_class}"
    result["lookup_source"] = str(lookup_meta.get("mode") or "")
    result["lookup_snapshot_age_seconds"] = int(
        lookup_meta.get("age_seconds") or 0
    )
    result["cache_expires_in"] = ctx.config.aram_augment_cache_seconds
    timing = result.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        result["timing"] = timing
    timing.update(
        {
            "cache_hit": False,
            "fallback": True,
            "fallback_error_class": error.error_class,
            "snapshot_age_seconds": int(snapshot.age_seconds),
            "response_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    )
    return result


def build_aram_augment_payload(
    ctx: AppContext,
    query: str,
    *,
    resolved_hero: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    hero = resolved_hero or find_champion_for_opgg(ctx, query)
    if not hero:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
    canonical_alias = str(hero.get("alias") or "").strip()
    if not canonical_alias:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
    lookup_meta = _champion_lookup_meta(ctx)
    snapshot = load_aram_payload_snapshot(ctx, canonical_alias)
    slug_candidates = _slug_candidates(hero)

    augment_future = _opgg_executor.submit(
        _fetch_augment_rows,
        ctx,
        slug_candidates,
    )
    build_future = _opgg_executor.submit(
        _fetch_optional_build,
        ctx,
        slug_candidates,
    )
    try:
        augment_result = augment_future.result()
    except AramRequiredUpstreamError as exc:
        try:
            build_future.result()
        except Exception:
            pass
        record_aram_payload_error(
            ctx,
            canonical_alias,
            exc.error_class,
            str(exc),
        )
        return _snapshot_fallback_payload(
            ctx,
            query=query,
            snapshot=snapshot,
            error=exc,
            lookup_meta=lookup_meta,
            started=started,
        )

    try:
        build_result = build_future.result()
    except Exception as exc:
        build_result = _empty_optional_build(
            status="unavailable",
            error_class=exc.__class__.__name__,
        )
    build_result = _merge_optional_snapshot(
        build_result,
        snapshot.payload if snapshot.ok else None,
        snapshot.age_seconds,
    )

    rows = augment_result["rows"]
    top_rows = rows[:10]
    payload = {
        "hero": copy.deepcopy(hero),
        "query": query,
        "rows": top_rows,
        "item_builds": build_result["item_builds"],
        "starter_items": build_result["starter_items"],
        "boots": build_result["boots"],
        "summoner_spells": build_result["summoner_spells"],
        "skill_order": build_result["skill_order"],
        "total": len(rows),
        "source": "opgg",
        "provider": "opgg",
        "source_url": augment_result["source_url"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stale": False,
        "snapshot_age_seconds": 0,
        "fallback_reason": "",
        "lookup_source": str(lookup_meta.get("mode") or ""),
        "lookup_snapshot_age_seconds": int(
            lookup_meta.get("age_seconds") or 0
        ),
        "cache_expires_in": ctx.config.aram_augment_cache_seconds,
        "timing": {
            "cache_hit": False,
            "fallback": False,
            "augment_ms": augment_result["duration_ms"],
            "augment_attempts": augment_result.get("attempts", 0),
            "augment_http_status": augment_result.get("http_status", 0),
            "build_ms": build_result["duration_ms"],
            "build_status": build_result["status"],
            "build_error_class": build_result.get("error_class", ""),
            "build_attempts": build_result.get("attempts", 0),
            "build_http_status": build_result.get("http_status", 0),
            "optional_snapshot_age_seconds": int(
                build_result.get("snapshot_age_seconds") or 0
            ),
            "upstream_total_ms": round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
        },
    }
    _captured_at, snapshot_write_error = save_aram_payload_snapshot(
        ctx,
        canonical_alias,
        payload,
    )
    payload["timing"]["snapshot_write_error"] = snapshot_write_error
    return payload


def _payload_copy_for_response(
    payload: Dict[str, Any],
    *,
    query: str,
    source: Optional[str],
    cache_ttl: int,
    cache_hit: bool,
    lookup_ms: float,
    response_ms: float,
    singleflight_shared: bool,
) -> Dict[str, Any]:
    result = copy.deepcopy(payload)
    result["query"] = query
    if source:
        if source == "cache":
            result["cache_origin"] = str(result.get("source") or "")
        result["source"] = source
    result["cache_expires_in"] = cache_ttl
    timing = result.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        result["timing"] = timing
    timing.update(
        {
            "cache_hit": cache_hit,
            "lookup_ms": round(lookup_ms, 1),
            "response_ms": round(response_ms, 1),
            "singleflight_shared": singleflight_shared,
        }
    )
    return result


async def query_aram_augments(ctx: AppContext, *, hero: str) -> Dict[str, Any]:
    request_started = time.perf_counter()
    lookup_started = time.perf_counter()
    resolved_hero = await asyncio.to_thread(find_champion_for_opgg, ctx, hero)
    lookup_ms = (time.perf_counter() - lookup_started) * 1000
    if not resolved_hero:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{hero}")
    canonical_alias = str(resolved_hero.get("alias") or "").strip().casefold()
    if not canonical_alias:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{hero}")
    cache_key = f"aram_augments:{canonical_alias}"
    cache_hit, cache_ttl = ctx.aram_augment_cache.get_with_remaining_ttl(cache_key)
    if isinstance(cache_hit, dict):
        return _payload_copy_for_response(
            cache_hit,
            query=hero,
            source="cache",
            cache_ttl=cache_ttl,
            cache_hit=True,
            lookup_ms=lookup_ms,
            response_ms=(time.perf_counter() - request_started) * 1000,
            singleflight_shared=False,
        )

    flight_key = (id(ctx), cache_key)
    with _payload_flights_lock:
        flight = _payload_flights.get(flight_key)
        owns_flight = flight is None
        if flight is None:
            flight = Future()
            _payload_flights[flight_key] = flight

    if not owns_flight:
        shared_payload = await asyncio.shield(asyncio.wrap_future(flight))
        return _payload_copy_for_response(
            shared_payload,
            query=hero,
            source=None,
            cache_ttl=ctx.config.aram_augment_cache_seconds,
            cache_hit=False,
            lookup_ms=lookup_ms,
            response_ms=(time.perf_counter() - request_started) * 1000,
            singleflight_shared=True,
        )

    try:
        second_cache_hit, second_cache_ttl = (
            ctx.aram_augment_cache.get_with_remaining_ttl(cache_key)
        )
        if isinstance(second_cache_hit, dict):
            flight.set_result(copy.deepcopy(second_cache_hit))
            return _payload_copy_for_response(
                second_cache_hit,
                query=hero,
                source="cache",
                cache_ttl=second_cache_ttl,
                cache_hit=True,
                lookup_ms=lookup_ms,
                response_ms=(time.perf_counter() - request_started) * 1000,
                singleflight_shared=False,
            )

        payload = await asyncio.to_thread(
            build_aram_augment_payload,
            ctx,
            hero,
            resolved_hero=resolved_hero,
        )
        cached_payload = copy.deepcopy(payload)
        ctx.aram_augment_cache.set(cache_key, cached_payload)
        flight.set_result(copy.deepcopy(cached_payload))
        return _payload_copy_for_response(
            payload,
            query=hero,
            source=None,
            cache_ttl=ctx.config.aram_augment_cache_seconds,
            cache_hit=False,
            lookup_ms=lookup_ms,
            response_ms=(time.perf_counter() - request_started) * 1000,
            singleflight_shared=False,
        )
    except asyncio.CancelledError:
        if not flight.done():
            flight.set_exception(
                RuntimeError("ARAM payload request was cancelled")
            )
        raise
    except Exception as exc:
        if not flight.done():
            flight.set_exception(exc)
        raise
    finally:
        with _payload_flights_lock:
            if _payload_flights.get(flight_key) is flight:
                _payload_flights.pop(flight_key, None)


def rarity_label(value: Any) -> str:
    try:
        rarity = int(value)
    except (TypeError, ValueError):
        return "-"
    return {1: "银", 2: "金", 3: "金", 4: "棱镜", 8: "金"}.get(
        rarity,
        str(rarity),
    )
