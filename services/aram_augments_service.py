import asyncio
import copy
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from core.context import AppContext
from services.opgg_client import opgg_request
from services.opgg_parser import (
    extract_opgg_augments,
    extract_opgg_core_builds,
    extract_opgg_item_rows,
    extract_opgg_skill_order,
    extract_opgg_summoner_spells,
)
from utils.http_client import fetch_json_url
from utils.text_utils import normalize_search_text


_payload_flights_lock = threading.Lock()
_payload_flights: Dict[Tuple[int, str], Future] = {}
_opgg_executor = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="aram-opgg",
)


def get_champion_lookup_sources(ctx: AppContext) -> List[Dict[str, Any]]:
    cached = ctx.aram_augment_cache.get("champions")
    if isinstance(cached, list):
        return cached
    hero_data = fetch_json_url(ctx.config.shard_hero_url)
    hero_list = hero_data.get("hero") if isinstance(hero_data, dict) else []
    champions: List[Dict[str, Any]] = []
    if isinstance(hero_list, list):
        for item in hero_list:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias") or "").strip()
            if not alias:
                continue
            champions.append(
                {
                    "alias": alias,
                    "slug": alias.lower(),
                    "name": str(item.get("name") or "").strip(),
                    "title": str(item.get("title") or "").strip(),
                    "keywords": str(item.get("keywords") or "").strip(),
                    "heroId": str(item.get("heroId") or "").strip(),
                }
            )
    ctx.aram_augment_cache.set("champions", champions)
    return champions


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
        haystack = normalize_search_text(",".join(str(hero.get(k) or "") for k in ("alias", "slug", "title", "name", "keywords")))
        if needle in haystack:
            return hero
    return None


def _slug_candidates(hero: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for value in [hero.get("slug"), hero.get("alias")]:
        slug = str(value or "").strip().lower()
        if slug and slug not in candidates:
            candidates.append(slug)
    if str(hero.get("alias") or "").casefold() == "monkeyking" and "wukong" not in candidates:
        candidates.insert(0, "wukong")
    return candidates


def _fetch_augment_rows(slug_candidates: List[str]) -> Dict[str, Any]:
    started = time.perf_counter()
    last_error = ""
    used_url = ""
    for slug in slug_candidates:
        url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/augments"
        try:
            response = opgg_request(url)
            used_url = response.url
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                continue
            rows = extract_opgg_augments(response.text)
            if rows:
                return {
                    "rows": rows,
                    "source_url": used_url,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            last_error = "页面中未找到强化符文数据"
        except Exception as exc:
            last_error = str(exc)
    raise HTTPException(status_code=503, detail=f"OP.GG 强化符文数据不可用：{last_error or '未知错误'}")


def _fetch_optional_build(slug_candidates: List[str]) -> Dict[str, Any]:
    started = time.perf_counter()
    result: Dict[str, Any] = {
        "item_builds": [],
        "starter_items": [],
        "boots": [],
        "summoner_spells": [],
        "skill_order": [],
        "status": "empty",
    }
    for slug in slug_candidates:
        build_url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/build"
        try:
            # Build data is supplementary. One shorter attempt keeps it from
            # extending the required augment request's retry budget.
            response = opgg_request(
                build_url,
                connect_timeout=2.0,
                read_timeout=4.5,
                attempts=1,
            )
            if response.status_code >= 400:
                result["status"] = "unavailable"
                continue
            result["item_builds"] = extract_opgg_core_builds(response.text)
            result["starter_items"] = extract_opgg_item_rows(response.text, "starter_items", limit=2, max_items=3)
            result["boots"] = extract_opgg_item_rows(response.text, "boots", limit=2, max_items=1)
            result["summoner_spells"] = extract_opgg_summoner_spells(response.text)
            result["skill_order"] = extract_opgg_skill_order(response.text)
            if any(result[key] for key in ("item_builds", "starter_items", "boots", "summoner_spells", "skill_order")):
                result["status"] = "ok"
                break
        except Exception:
            result["status"] = "unavailable"
            continue
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
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
    slug_candidates = _slug_candidates(hero)
    augment_future = _opgg_executor.submit(
        _fetch_augment_rows,
        slug_candidates,
    )
    build_future = _opgg_executor.submit(
        _fetch_optional_build,
        slug_candidates,
    )
    augment_result = augment_future.result()
    try:
        build_result = build_future.result()
    except Exception:
        build_result = {
            "item_builds": [],
            "starter_items": [],
            "boots": [],
            "summoner_spells": [],
            "skill_order": [],
            "status": "unavailable",
            "duration_ms": 0.0,
        }

    rows = augment_result["rows"]
    top_rows = rows[:10]
    return {
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
        "source_url": augment_result["source_url"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cache_expires_in": ctx.config.aram_augment_cache_seconds,
        "timing": {
            "cache_hit": False,
            "augment_ms": augment_result["duration_ms"],
            "build_ms": build_result["duration_ms"],
            "build_status": build_result["status"],
            "upstream_total_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


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
        # Close the small race where another flight populated the cache after
        # our first lookup but immediately before this flight was registered.
        second_cache_hit, second_cache_ttl = ctx.aram_augment_cache.get_with_remaining_ttl(cache_key)
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
            flight.set_exception(RuntimeError("ARAM payload request was cancelled"))
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
    return {1: "银", 2: "金", 3: "金", 4: "棱镜", 8: "金"}.get(rarity, str(rarity))
