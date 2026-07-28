from __future__ import annotations

import copy
import hashlib
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from services.persistent_snapshot_store import PersistentSnapshotStore, SnapshotLoadResult
from services.upstream_http_client import UpstreamHttpClient, UpstreamResponse


HERO_CATALOG_SOURCE_ID = "lol-hero-list"
DEFAULT_HERO_SNAPSHOT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_ARAM_SNAPSHOT_MAX_AGE_SECONDS = 24 * 60 * 60
OPGG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def hero_snapshot_max_age_seconds() -> int:
    return _env_int(
        "SHARD_SNAPSHOT_MAX_AGE_SECONDS",
        DEFAULT_HERO_SNAPSHOT_MAX_AGE_SECONDS,
        60,
        365 * 24 * 60 * 60,
    )


def aram_snapshot_max_age_seconds() -> int:
    return _env_int(
        "ARAM_SNAPSHOT_MAX_AGE_SECONDS",
        DEFAULT_ARAM_SNAPSHOT_MAX_AGE_SECONDS,
        60,
        30 * 24 * 60 * 60,
    )


def upstream_client(ctx: Any) -> UpstreamHttpClient:
    client = getattr(ctx, "upstream_http_client", None)
    if isinstance(client, UpstreamHttpClient) or (
        client is not None and callable(getattr(client, "request", None))
    ):
        return client
    client = UpstreamHttpClient(logger=getattr(ctx, "logger", None))
    setattr(ctx, "upstream_http_client", client)
    return client


def snapshot_store(ctx: Any) -> PersistentSnapshotStore:
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


def safe_error_class(response: UpstreamResponse) -> str:
    error = getattr(response, "error", None)
    return str(
        getattr(error, "error_class", "")
        or response.status
        or "unavailable"
    )


def safe_error_message(response: UpstreamResponse) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "message", "") or "")[:300]


def _validate_hero_data(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("hero data must be an object")
    heroes = value.get("hero")
    if not isinstance(heroes, list) or not heroes:
        raise ValueError("hero data must contain a non-empty hero list")
    if not any(
        isinstance(item, dict) and str(item.get("alias") or "").strip()
        for item in heroes
    ):
        raise ValueError("hero list has no usable aliases")


def _champions_from_payload(value: Any) -> List[Dict[str, Any]]:
    heroes = value.get("hero") if isinstance(value, dict) else []
    champions: List[Dict[str, Any]] = []
    if not isinstance(heroes, list):
        return champions
    for item in heroes:
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
    return champions


def _snapshot_headers(snapshot: SnapshotLoadResult) -> tuple[str, str]:
    if not snapshot.ok:
        return "", ""
    return (
        str(snapshot.metadata.get("etag") or ""),
        str(snapshot.metadata.get("last_modified") or ""),
    )


def _save_json_snapshot(
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


def _record_error(
    store: PersistentSnapshotStore,
    source_id: str,
    error_class: str,
    message: str = "",
) -> None:
    try:
        store.record_refresh_error(source_id, error_class, message)
    except Exception:
        return


def load_champion_catalog(ctx: Any) -> Dict[str, Any]:
    cached = ctx.aram_augment_cache.get("champion_catalog")
    if isinstance(cached, dict) and isinstance(cached.get("champions"), list):
        return copy.deepcopy(cached)

    store = snapshot_store(ctx)
    snapshot = store.load(
        HERO_CATALOG_SOURCE_ID,
        max_age_seconds=hero_snapshot_max_age_seconds(),
    )
    etag, last_modified = _snapshot_headers(snapshot)
    response = upstream_client(ctx).get_json(
        HERO_CATALOG_SOURCE_ID,
        ctx.config.shard_hero_url,
        etag=etag,
        last_modified=last_modified,
        validate=_validate_hero_data,
    )

    payload: Any = None
    mode = "live"
    captured_at = ""
    age_seconds = 0
    error_class = ""
    snapshot_write_error = ""
    conditional_not_modified = False

    if response.ok and response.status == "not_modified" and snapshot.ok:
        payload = snapshot.payload
        conditional_not_modified = True
        captured_at, snapshot_write_error = _save_json_snapshot(
            store,
            HERO_CATALOG_SOURCE_ID,
            payload,
            response,
            fallback_etag=etag,
            fallback_last_modified=last_modified,
        )
        captured_at = captured_at or snapshot.captured_at
    elif response.ok and response.data is not None:
        payload = response.data
        captured_at, snapshot_write_error = _save_json_snapshot(
            store,
            HERO_CATALOG_SOURCE_ID,
            payload,
            response,
        )
        captured_at = captured_at or datetime.now().isoformat(timespec="seconds")
    else:
        error_class = safe_error_class(response)
        _record_error(
            store,
            HERO_CATALOG_SOURCE_ID,
            error_class,
            safe_error_message(response),
        )
        if snapshot.ok:
            payload = snapshot.payload
            mode = "snapshot" if response.status == "circuit_open" else "stale"
            captured_at = snapshot.captured_at
            age_seconds = snapshot.age_seconds
        else:
            raise HTTPException(
                status_code=503,
                detail=(
                    "英雄基础数据暂不可用"
                    f"（{HERO_CATALOG_SOURCE_ID}: {error_class}；"
                    f"本地快照状态：{snapshot.status}）"
                ),
            )

    champions = _champions_from_payload(payload)
    if not champions:
        raise HTTPException(status_code=503, detail="英雄基础数据中没有可用英雄")

    result = {
        "champions": champions,
        "mode": mode,
        "captured_at": captured_at,
        "age_seconds": age_seconds,
        "error_class": error_class,
        "snapshot_status": snapshot.status,
        "snapshot_write_error": snapshot_write_error,
        "conditional_not_modified": conditional_not_modified,
    }
    ctx.aram_augment_cache.set("champion_catalog", copy.deepcopy(result))
    return result


def safe_source_suffix(value: str) -> str:
    normalized = _SAFE_ID_RE.sub("-", str(value or "").strip()).strip("-._")
    if normalized:
        return normalized[:72]
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def opgg_source_id(page_kind: str, slug: str) -> str:
    return f"opgg-aram-{safe_source_suffix(page_kind)}-{safe_source_suffix(slug)}"[:128]


def request_opgg_html(
    ctx: Any,
    *,
    page_kind: str,
    slug: str,
    url: str,
    attempts: int = 2,
    connect_timeout: float = 3.0,
    read_timeout: float = 7.0,
) -> UpstreamResponse:
    return upstream_client(ctx).request(
        opgg_source_id(page_kind, slug),
        url,
        headers=OPGG_HEADERS,
        parse_json=False,
        attempts=attempts,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        singleflight=True,
    )


def aram_payload_source_id(alias: str) -> str:
    return f"aram-mayhem-{safe_source_suffix(alias.casefold())}"[:128]


def load_aram_payload_snapshot(ctx: Any, alias: str) -> SnapshotLoadResult:
    return snapshot_store(ctx).load(
        aram_payload_source_id(alias),
        max_age_seconds=aram_snapshot_max_age_seconds(),
    )


def save_aram_payload_snapshot(
    ctx: Any,
    alias: str,
    payload: Dict[str, Any],
) -> tuple[str, str]:
    source_id = aram_payload_source_id(alias)
    try:
        result = snapshot_store(ctx).save(
            source_id,
            payload,
            {
                "provider": "opgg",
                "canonical_alias": str(alias or "").strip(),
            },
        )
        return str(result.get("captured_at") or ""), ""
    except Exception as exc:
        return "", exc.__class__.__name__


def record_aram_payload_error(
    ctx: Any,
    alias: str,
    error_class: str,
    message: str = "",
) -> None:
    _record_error(
        snapshot_store(ctx),
        aram_payload_source_id(alias),
        error_class,
        message,
    )
