from __future__ import annotations

import asyncio
import copy
import os
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from core.context import AppContext
from services.persistent_snapshot_store import PersistentSnapshotStore, SnapshotLoadResult
from services.upstream_http_client import UpstreamHttpClient, UpstreamResponse
from utils.text_utils import normalize_search_text


SHARD_DATA_SOURCE_ID = "lol-shard-data"
SHARD_HERO_SOURCE_ID = "lol-hero-list"
DEFAULT_SHARD_SNAPSHOT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_SHARD_DATA_URL = (
    "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json"
)
SHARD_DATA_MIRRORS = (
    "https://cdn.jsdelivr.net/gh/badspacebar/release@master/files/shards.json",
    "https://testingcf.jsdelivr.net/gh/badspacebar/release@master/files/shards.json",
    "https://ghfast.top/https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json",
)



@dataclass(frozen=True)
class _LoadedUpstreamSource:
    payload: Any
    mode: str
    captured_at: str
    age_seconds: int
    attempts: int
    status_code: int
    etag: str
    last_modified: str
    error_class: str = ""
    snapshot_status: str = ""
    conditional_not_modified: bool = False
    snapshot_write_error: str = ""
    mirror_used: str = ""


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _snapshot_max_age_seconds() -> int:
    return _env_int(
        "SHARD_SNAPSHOT_MAX_AGE_SECONDS",
        DEFAULT_SHARD_SNAPSHOT_MAX_AGE_SECONDS,
        60,
        365 * 24 * 60 * 60,
    )


def _upstream_client(ctx: AppContext) -> UpstreamHttpClient:
    client = getattr(ctx, "upstream_http_client", None)
    if isinstance(client, UpstreamHttpClient) or (
        client is not None and callable(getattr(client, "get_json", None))
    ):
        return client
    client = UpstreamHttpClient(logger=getattr(ctx, "logger", None))
    setattr(ctx, "upstream_http_client", client)
    return client


def _snapshot_store(ctx: AppContext) -> PersistentSnapshotStore:
    store = getattr(ctx, "upstream_snapshot_store", None)
    if isinstance(store, PersistentSnapshotStore) or (
        store is not None
        and callable(getattr(store, "load", None))
        and callable(getattr(store, "save", None))
    ):
        return store
    store = PersistentSnapshotStore()
    setattr(ctx, "upstream_snapshot_store", store)
    return store


def _validate_shard_data(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("shard data must be a non-empty object")
    if not any(isinstance(item, dict) for item in value.values()):
        raise ValueError("shard data has no champion records")


def _validate_hero_data(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("hero data must be an object")
    hero_list = value.get("hero")
    if not isinstance(hero_list, list) or not hero_list:
        raise ValueError("hero data must contain a non-empty hero list")
    if not any(
        isinstance(item, dict) and str(item.get("alias") or "").strip()
        for item in hero_list
    ):
        raise ValueError("hero list has no usable aliases")


def _snapshot_headers(snapshot: SnapshotLoadResult) -> tuple[str, str]:
    if not snapshot.ok:
        return "", ""
    return (
        str(snapshot.metadata.get("etag") or ""),
        str(snapshot.metadata.get("last_modified") or ""),
    )


def _safe_error_class(response: UpstreamResponse) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "error_class", "") or response.status or "unavailable")


def _safe_error_message(response: UpstreamResponse) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "message", "") or "")[:300]


def _record_refresh_error(
    store: PersistentSnapshotStore,
    source_id: str,
    response: UpstreamResponse,
) -> None:
    try:
        store.record_refresh_error(
            source_id,
            _safe_error_class(response),
            _safe_error_message(response),
        )
    except Exception:
        return


def _save_snapshot(
    store: PersistentSnapshotStore,
    source_id: str,
    payload: Any,
    response: UpstreamResponse,
    *,
    fallback_etag: str = "",
    fallback_last_modified: str = "",
) -> tuple[str, str]:
    try:
        result = store.save(
            source_id,
            payload,
            {
                "etag": str(response.etag or fallback_etag or ""),
                "last_modified": str(
                    response.last_modified or fallback_last_modified or ""
                ),
                "http_status": int(response.status_code or 0),
                "upstream_status": str(response.status or ""),
            },
        )
        return str(result.get("captured_at") or ""), ""
    except Exception as exc:
        return "", exc.__class__.__name__


def _try_shard_data_mirrors(
    ctx: AppContext,
    *,
    source_id: str,
    url: str,
    validate: Callable[[Any], None],
) -> tuple[UpstreamResponse | None, str]:
    # Only the canonical public dataset is mirrored. Custom source URLs are
    # never rewritten or forwarded to a third-party proxy.
    if source_id != SHARD_DATA_SOURCE_ID or url != DEFAULT_SHARD_DATA_URL:
        return None, ""

    client = _upstream_client(ctx)
    for index, mirror_url in enumerate(SHARD_DATA_MIRRORS):
        mirror_id = f"{source_id}-mirror-{index + 1}"
        candidate = client.get_json(
            mirror_id,
            mirror_url,
            validate=validate,
            attempts=1,
            connect_timeout=4,
            read_timeout=10,
        )
        if candidate.ok and candidate.data is not None:
            # Validators from another host must not be reused for primary 304s.
            return replace(candidate, etag="", last_modified=""), f"mirror-{index + 1}"
        logger = getattr(ctx, "logger", None)
        if logger is not None:
            logger.warning(
                "shard data mirror %s unavailable: %s",
                index + 1,
                _safe_error_class(candidate),
            )
    return None, ""


def _load_one_source(
    ctx: AppContext,
    *,
    source_id: str,
    url: str,
    validate: Callable[[Any], None],
) -> _LoadedUpstreamSource:
    store = _snapshot_store(ctx)
    max_age = _snapshot_max_age_seconds()
    snapshot = store.load(source_id, max_age_seconds=max_age)
    etag, last_modified = _snapshot_headers(snapshot)

    response = _upstream_client(ctx).get_json(
        source_id,
        url,
        etag=etag,
        last_modified=last_modified,
        validate=validate,
    )
    mirror_used = ""
    if not response.ok:
        alternate, mirror_used = _try_shard_data_mirrors(
            ctx, source_id=source_id, url=url, validate=validate,
        )
        if alternate is not None:
            response = alternate

    if response.ok:
        if response.status == "not_modified":
            if not snapshot.ok:
                # A conditional 304 is unusable without the matching local body.
                response = _upstream_client(ctx).get_json(
                    source_id,
                    url,
                    validate=validate,
                    singleflight=False,
                )
                if not response.ok:
                    _record_refresh_error(store, source_id, response)
                else:
                    captured_at, write_error = _save_snapshot(
                        store,
                        source_id,
                        response.data,
                        response,
                    )
                    return _LoadedUpstreamSource(
                        payload=response.data,
                        mode="live",
                        captured_at=(
                            captured_at
                            or datetime.now().isoformat(timespec="seconds")
                        ),
                        age_seconds=0,
                        attempts=response.attempts,
                        status_code=response.status_code,
                        etag=response.etag,
                        last_modified=response.last_modified,
                        snapshot_status=snapshot.status,
                        snapshot_write_error=write_error,
                        mirror_used=mirror_used,
                    )
            else:
                captured_at, write_error = _save_snapshot(
                    store,
                    source_id,
                    snapshot.payload,
                    response,
                    fallback_etag=etag,
                    fallback_last_modified=last_modified,
                )
                return _LoadedUpstreamSource(
                    payload=snapshot.payload,
                    mode="live",
                    captured_at=captured_at or snapshot.captured_at,
                    age_seconds=0,
                    attempts=response.attempts,
                    status_code=response.status_code,
                    etag=response.etag or etag,
                    last_modified=response.last_modified or last_modified,
                    snapshot_status=snapshot.status,
                    conditional_not_modified=True,
                    snapshot_write_error=write_error,
                    mirror_used=mirror_used,
                )
        elif response.data is not None:
            captured_at, write_error = _save_snapshot(
                store,
                source_id,
                response.data,
                response,
            )
            return _LoadedUpstreamSource(
                payload=response.data,
                mode="live",
                captured_at=(
                    captured_at or datetime.now().isoformat(timespec="seconds")
                ),
                age_seconds=0,
                attempts=response.attempts,
                status_code=response.status_code,
                etag=response.etag,
                last_modified=response.last_modified,
                snapshot_status=snapshot.status,
                snapshot_write_error=write_error,
                mirror_used=mirror_used,
            )

    _record_refresh_error(store, source_id, response)
    if snapshot.ok:
        mode = "snapshot" if response.status == "circuit_open" else "stale"
        return _LoadedUpstreamSource(
            payload=snapshot.payload,
            mode=mode,
            captured_at=snapshot.captured_at,
            age_seconds=snapshot.age_seconds,
            attempts=response.attempts,
            status_code=response.status_code,
            etag=etag,
            last_modified=last_modified,
            error_class=_safe_error_class(response),
            snapshot_status=snapshot.status,
        )

    error_class = _safe_error_class(response)
    raise HTTPException(
        status_code=503,
        detail=(
            f"合集基础数据暂不可用（{source_id}: {error_class}；"
            f"本地快照状态：{snapshot.status}）"
        ),
    )


def _source_detail(source: _LoadedUpstreamSource) -> Dict[str, Any]:
    return {
        "mode": source.mode,
        "captured_at": source.captured_at,
        "age_seconds": source.age_seconds,
        "attempts": source.attempts,
        "http_status": source.status_code,
        "etag_present": bool(source.etag),
        "last_modified_present": bool(source.last_modified),
        "error_class": source.error_class,
        "snapshot_status": source.snapshot_status,
        "conditional_not_modified": source.conditional_not_modified,
        "snapshot_write_error": source.snapshot_write_error,
        "mirror_used": source.mirror_used,
    }


def _overall_mode(*sources: _LoadedUpstreamSource) -> str:
    modes = {source.mode for source in sources}
    if "stale" in modes:
        return "stale"
    if "snapshot" in modes:
        return "snapshot"
    return "live"


def _fallback_reason(*sources: _LoadedUpstreamSource) -> str:
    values = [
        f"{source_id}:{source.error_class}"
        for source_id, source in (
            (SHARD_DATA_SOURCE_ID, sources[0]),
            (SHARD_HERO_SOURCE_ID, sources[1]),
        )
        if source.error_class
    ]
    return ", ".join(values)


def load_shard_sources(ctx: AppContext) -> Dict[str, Any]:
    cached = ctx.shard_cache.get("sources")
    if isinstance(cached, dict):
        return copy.deepcopy(cached)

    shard_source = _load_one_source(
        ctx,
        source_id=SHARD_DATA_SOURCE_ID,
        url=ctx.config.shard_data_url,
        validate=_validate_shard_data,
    )
    hero_source = _load_one_source(
        ctx,
        source_id=SHARD_HERO_SOURCE_ID,
        url=ctx.config.shard_hero_url,
        validate=_validate_hero_data,
    )

    shard_data = shard_source.payload
    hero_data = hero_source.payload
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

    mode = _overall_mode(shard_source, hero_source)
    captured_values = [
        value
        for value in (shard_source.captured_at, hero_source.captured_at)
        if value
    ]
    payload = {
        "shards": shards,
        "champions": champions,
        "updated_at": (
            min(captured_values)
            if captured_values
            else datetime.now().isoformat(timespec="seconds")
        ),
        "source": mode,
        "provider": "badspacebar+gtimg",
        "stale": mode in {"stale", "snapshot"},
        "snapshot_age_seconds": max(
            shard_source.age_seconds,
            hero_source.age_seconds,
        ),
        "fallback_reason": _fallback_reason(shard_source, hero_source),
        "source_details": {
            SHARD_DATA_SOURCE_ID: _source_detail(shard_source),
            SHARD_HERO_SOURCE_ID: _source_detail(hero_source),
        },
    }
    ctx.shard_cache.set("sources", copy.deepcopy(payload))
    return payload


def find_shard_champion(
    query: str,
    champions: List[Dict[str, Any]],
    shards: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
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
        haystack = normalize_search_text(
            ",".join(
                str(hero.get(key) or "")
                for key in ("alias", "title", "name", "keywords")
            )
        )
        if needle in haystack:
            return hero
    return None


def build_shard_payload(ctx: AppContext, query: str) -> Dict[str, Any]:
    sources = load_shard_sources(ctx)
    shards = (
        sources.get("shards")
        if isinstance(sources.get("shards"), dict)
        else {}
    )
    champions = (
        sources.get("champions")
        if isinstance(sources.get("champions"), list)
        else []
    )
    hero = find_shard_champion(query, champions, shards)
    if not hero:
        raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
    stat = shards.get(hero.get("alias")) if isinstance(shards, dict) else None
    if not isinstance(stat, dict):
        raise HTTPException(
            status_code=404,
            detail=f"暂无 {hero.get('title') or hero.get('alias')} 的合集数据",
        )
    rows = stat.get("shards") if isinstance(stat.get("shards"), list) else []
    clean_rows = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        clean_rows.append(
            {
                "name": str(
                    item.get("name") or item.get("id") or "未知合集"
                ).strip(),
                "id": str(item.get("id") or "").strip(),
                "pick_rate": item.get("pick_rate"),
                "win_rate": item.get("win_rate"),
            }
        )
    clean_rows.sort(
        key=lambda row: float(row.get("pick_rate") or 0),
        reverse=True,
    )
    return {
        "hero": hero,
        "query": query,
        "pick_rate": stat.get("pick_rate"),
        "win_rate": stat.get("win_rate"),
        "count": len(clean_rows),
        "rows": clean_rows,
        "source": sources.get("source") or "live",
        "provider": "badspacebar",
        "stale": bool(sources.get("stale")),
        "snapshot_age_seconds": int(
            sources.get("snapshot_age_seconds") or 0
        ),
        "fallback_reason": str(sources.get("fallback_reason") or ""),
        "source_details": copy.deepcopy(sources.get("source_details") or {}),
        "updated_at": (
            sources.get("updated_at")
            or datetime.now().isoformat(timespec="seconds")
        ),
        "cache_expires_in": ctx.config.shard_cache_seconds,
    }


async def query_shard(ctx: AppContext, *, hero: str) -> Dict[str, Any]:
    cache_key = f"shard:{hero}"
    cache_hit, cache_ttl = ctx.shard_cache.get_with_remaining_ttl(cache_key)
    if isinstance(cache_hit, dict):
        result = copy.deepcopy(cache_hit)
        result["cache_origin"] = str(result.get("source") or "")
        result["source"] = "cache"
        result["cache_expires_in"] = cache_ttl
        return result
    payload = await asyncio.to_thread(build_shard_payload, ctx, hero)
    ctx.shard_cache.set(cache_key, copy.deepcopy(payload))
    return payload
