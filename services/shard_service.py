import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from core.context import AppContext
from utils.http_client import fetch_json_url
from utils.text_utils import normalize_search_text


def load_shard_sources(ctx: AppContext) -> Dict[str, Any]:
    cached = ctx.shard_cache.get("sources")
    if isinstance(cached, dict):
        return cached
    shard_data = fetch_json_url(ctx.config.shard_data_url)
    hero_data = fetch_json_url(ctx.config.shard_hero_url)
    shards = shard_data if isinstance(shard_data, dict) else {}
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
                    "name": str(item.get("name") or "").strip(),
                    "title": str(item.get("title") or "").strip(),
                    "keywords": str(item.get("keywords") or "").strip(),
                }
            )
    payload = {
        "shards": shards,
        "champions": champions,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ctx.shard_cache.set("sources", payload)
    return payload


def find_shard_champion(query: str, champions: List[Dict[str, Any]], shards: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    needle = normalize_search_text(query)
    if not needle:
        return None
    with_data = [hero for hero in champions if hero.get("alias") in shards]
    for hero in with_data:
        if needle in {
            normalize_search_text(hero.get("alias")),
            normalize_search_text(hero.get("title")),
            normalize_search_text(hero.get("name")),
        }:
            return hero
    for hero in with_data:
        haystack = normalize_search_text(",".join(str(hero.get(k) or "") for k in ("alias", "title", "name", "keywords")))
        if needle in haystack:
            return hero
    return None


def build_shard_payload(ctx: AppContext, query: str) -> Dict[str, Any]:
    sources = load_shard_sources(ctx)
    shards = sources.get("shards") if isinstance(sources.get("shards"), dict) else {}
    champions = sources.get("champions") if isinstance(sources.get("champions"), list) else []
    hero = find_shard_champion(query, champions, shards)
    if not hero:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
    stat = shards.get(hero.get("alias")) if isinstance(shards, dict) else None
    if not isinstance(stat, dict):
        raise HTTPException(status_code=404, detail=f"暂无 {hero.get('title') or hero.get('alias')} 的合集数据")
    rows = stat.get("shards") if isinstance(stat.get("shards"), list) else []
    clean_rows = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        clean_rows.append(
            {
                "name": str(item.get("name") or item.get("id") or "未知合集").strip(),
                "id": str(item.get("id") or "").strip(),
                "pick_rate": item.get("pick_rate"),
                "win_rate": item.get("win_rate"),
            }
        )
    clean_rows.sort(key=lambda row: float(row.get("pick_rate") or 0), reverse=True)
    return {
        "hero": hero,
        "query": query,
        "pick_rate": stat.get("pick_rate"),
        "win_rate": stat.get("win_rate"),
        "count": len(clean_rows),
        "rows": clean_rows,
        "source": "badspacebar",
        "updated_at": sources.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cache_expires_in": ctx.config.shard_cache_seconds,
    }


async def query_shard(ctx: AppContext, *, hero: str) -> Dict[str, Any]:
    cache_key = f"shard:{hero}"
    cache_hit, cache_ttl = ctx.shard_cache.get_with_remaining_ttl(cache_key)
    if isinstance(cache_hit, dict):
        cache_hit["source"] = "cache"
        cache_hit["cache_expires_in"] = cache_ttl
        return cache_hit
    payload = await asyncio.to_thread(build_shard_payload, ctx, hero)
    ctx.shard_cache.set(cache_key, payload)
    return payload
