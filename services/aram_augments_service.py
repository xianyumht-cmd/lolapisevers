import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

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


def build_aram_augment_payload(ctx: AppContext, query: str) -> Dict[str, Any]:
    hero = find_champion_for_opgg(ctx, query)
    if not hero:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
    slug_candidates = []
    for value in [hero.get("slug"), hero.get("alias")]:
        slug = str(value or "").strip().lower()
        if slug and slug not in slug_candidates:
            slug_candidates.append(slug)
    if hero.get("alias") == "MonkeyKing" and "wukong" not in slug_candidates:
        slug_candidates.insert(0, "wukong")

    last_error = ""
    rows: List[Dict[str, Any]] = []
    item_builds: List[Dict[str, Any]] = []
    starter_items: List[Dict[str, Any]] = []
    boots: List[Dict[str, Any]] = []
    summoner_spells: List[Dict[str, str]] = []
    skill_order: List[Dict[str, str]] = []
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
                break
            last_error = "页面中未找到强化符文数据"
        except Exception as exc:
            last_error = str(exc)
    if not rows:
        raise HTTPException(status_code=503, detail=f"OP.GG 强化符文数据不可用：{last_error or '未知错误'}")

    for slug in slug_candidates:
        build_url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/build"
        try:
            response = opgg_request(build_url)
            if response.status_code >= 400:
                continue
            item_builds = extract_opgg_core_builds(response.text)
            starter_items = extract_opgg_item_rows(response.text, "starter_items", limit=2, max_items=3)
            boots = extract_opgg_item_rows(response.text, "boots", limit=2, max_items=1)
            summoner_spells = extract_opgg_summoner_spells(response.text)
            skill_order = extract_opgg_skill_order(response.text)
            if item_builds or starter_items or boots or summoner_spells or skill_order:
                break
        except Exception:
            continue
    top_rows = rows[:10]
    return {
        "hero": hero,
        "query": query,
        "rows": top_rows,
        "item_builds": item_builds,
        "starter_items": starter_items,
        "boots": boots,
        "summoner_spells": summoner_spells,
        "skill_order": skill_order,
        "total": len(rows),
        "source": "opgg",
        "source_url": used_url,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cache_expires_in": ctx.config.aram_augment_cache_seconds,
    }


async def query_aram_augments(ctx: AppContext, *, hero: str) -> Dict[str, Any]:
    cache_key = f"aram_augments:{hero}"
    cache_hit, cache_ttl = ctx.aram_augment_cache.get_with_remaining_ttl(cache_key)
    if isinstance(cache_hit, dict):
        cache_hit["source"] = "cache"
        cache_hit["cache_expires_in"] = cache_ttl
        return cache_hit
    payload = await asyncio.to_thread(build_aram_augment_payload, ctx, hero)
    ctx.aram_augment_cache.set(cache_key, payload)
    return payload


def rarity_label(value: Any) -> str:
    try:
        rarity = int(value)
    except (TypeError, ValueError):
        return "-"
    return {1: "银", 2: "金", 3: "金", 4: "棱镜", 8: "金"}.get(rarity, str(rarity))
