from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from services.aram_upstream_state import (
    aram_snapshot_max_age_seconds,
    hero_snapshot_max_age_seconds,
)
from services.lolban_service import (
    LOL_BAN_SNAPSHOT_SOURCE_ID,
    STALE_CACHE_SECONDS,
    get_lolban_health,
)
from services.shard_service import SHARD_DATA_SOURCE_ID, SHARD_HERO_SOURCE_ID


OBSERVABILITY_SCHEMA_VERSION = "query-observability.v1"
_DYNAMIC_ARAM_SNAPSHOT_PREFIX = "aram-mayhem-"
_DYNAMIC_ARAM_AUGMENT_PREFIX = "opgg-aram-augments-"
_DYNAMIC_ARAM_BUILD_PREFIX = "opgg-aram-build-"
_SAFE_ERROR_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_DYNAMIC_SNAPSHOT_SCAN = 2048
_MAX_ERROR_CLASSES = 12


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error_class(value: Any) -> str:
    text = _SAFE_ERROR_RE.sub("_", str(value or "").strip())[:96]
    return text or ""


def _safe_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_non_negative_float(value: Any) -> float:
    try:
        return max(0.0, round(float(value or 0.0), 3))
    except (TypeError, ValueError):
        return 0.0


def _cache_size(value: Any) -> int:
    try:
        return max(0, int(len(value)))
    except Exception:
        return 0


def _cache_contains(cache: Any, key: str) -> bool:
    try:
        contains = getattr(cache, "contains", None)
        if callable(contains):
            return bool(contains(key))
        getter = getattr(cache, "get", None)
        return bool(callable(getter) and getter(key) is not None)
    except Exception:
        return False


def _client_state(ctx: Any) -> tuple[Dict[str, Dict[str, Any]], float]:
    client = getattr(ctx, "upstream_http_client", None)
    if client is None:
        return {}, 0.0
    try:
        state_fn = getattr(client, "state", None)
        values = state_fn() if callable(state_fn) else {}
        states = values if isinstance(values, dict) else {}
    except Exception:
        states = {}
    try:
        monotonic_fn = getattr(client, "monotonic_fn", None)
        now = float(monotonic_fn()) if callable(monotonic_fn) else 0.0
    except Exception:
        now = 0.0
    return {
        str(source): dict(raw)
        for source, raw in states.items()
        if isinstance(raw, dict)
    }, now


def _seconds_since(now: float, value: Any) -> Optional[float]:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    if now <= 0 or numeric <= 0 or numeric > now:
        return None
    return round(now - numeric, 3)


def _safe_circuit(raw: Optional[Mapping[str, Any]], now: float) -> Dict[str, Any]:
    source = dict(raw or {})
    state = "open" if str(source.get("circuit_state") or "").lower() == "open" else "closed"
    return {
        "state": state,
        "consecutive_failures": _safe_non_negative_int(
            source.get("consecutive_failures")
        ),
        "open_remaining_seconds": _safe_non_negative_float(
            source.get("open_remaining_seconds")
        ),
        "in_flight": bool(source.get("in_flight")),
        "last_error_class": _safe_error_class(source.get("last_error_class")),
        "seconds_since_last_error": _seconds_since(
            now,
            source.get("last_error_at_monotonic"),
        ),
        "seconds_since_last_success": _seconds_since(
            now,
            source.get("last_success_at_monotonic"),
        ),
    }


def _safe_snapshot(
    store: Any,
    source_id: str,
    max_age_seconds: int,
) -> Dict[str, Any]:
    try:
        status_fn = getattr(store, "status", None)
        raw = (
            status_fn(source_id, max_age_seconds=max_age_seconds)
            if callable(status_fn)
            else {}
        )
        source = raw if isinstance(raw, dict) else {}
    except Exception as exc:
        source = {
            "snapshot_status": "unavailable",
            "snapshot_ok": False,
            "last_refresh_error_class": type(exc).__name__,
        }
    status = str(source.get("snapshot_status") or "missing").strip().lower()
    if status not in {
        "hit",
        "missing",
        "expired",
        "corrupt",
        "incompatible",
        "unavailable",
        "restored",
        "saved",
        "empty",
        "disabled",
        "write_error",
        "load_error",
        "invalid_payload",
    }:
        status = "unavailable"
    return {
        "available": bool(source.get("snapshot_ok")),
        "status": status,
        "captured_at": str(source.get("captured_at") or ""),
        "age_seconds": _safe_non_negative_int(source.get("age_seconds")),
        "max_age_seconds": _safe_non_negative_int(max_age_seconds),
        "last_success_at": str(source.get("last_success_at") or ""),
        "last_error_at": str(source.get("last_refresh_error_at") or ""),
        "last_error_class": _safe_error_class(
            source.get("last_refresh_error_class")
        ),
    }


def _source_mode(
    *,
    cache_active: bool,
    circuit: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> str:
    if cache_active:
        return "cache"
    snapshot_available = bool(snapshot.get("available"))
    if circuit.get("state") == "open":
        return "snapshot" if snapshot_available else "unavailable"
    if circuit.get("last_error_class"):
        return "stale" if snapshot_available else "unavailable"
    if circuit.get("seconds_since_last_success") is not None:
        return "live"
    if snapshot_available:
        return "snapshot"
    return "unavailable"


def _static_source(
    *,
    public_name: str,
    source_id: str,
    cache_active: bool,
    states: Mapping[str, Mapping[str, Any]],
    monotonic_now: float,
    store: Any,
    max_age_seconds: int,
) -> Dict[str, Any]:
    circuit = _safe_circuit(states.get(source_id), monotonic_now)
    snapshot = _safe_snapshot(store, source_id, max_age_seconds)
    return {
        "name": public_name,
        "mode": _source_mode(
            cache_active=cache_active,
            circuit=circuit,
            snapshot=snapshot,
        ),
        "cache_active": cache_active,
        "circuit": circuit,
        "snapshot": snapshot,
    }


def _aggregate_circuits(
    states: Mapping[str, Mapping[str, Any]],
    prefixes: Iterable[str],
    monotonic_now: float,
) -> Dict[str, Any]:
    prefix_tuple = tuple(prefixes)
    selected = [
        _safe_circuit(raw, monotonic_now)
        for source_id, raw in states.items()
        if str(source_id).startswith(prefix_tuple)
    ]
    errors = sorted(
        {
            str(item.get("last_error_class") or "")
            for item in selected
            if item.get("last_error_class")
        }
    )[:_MAX_ERROR_CLASSES]
    success_ages = [
        float(item["seconds_since_last_success"])
        for item in selected
        if item.get("seconds_since_last_success") is not None
    ]
    error_ages = [
        float(item["seconds_since_last_error"])
        for item in selected
        if item.get("seconds_since_last_error") is not None
    ]
    return {
        "observed_sources": len(selected),
        "circuit_open_count": sum(
            1 for item in selected if item.get("state") == "open"
        ),
        "in_flight_count": sum(1 for item in selected if item.get("in_flight")),
        "max_consecutive_failures": max(
            (_safe_non_negative_int(item.get("consecutive_failures")) for item in selected),
            default=0,
        ),
        "last_error_classes": errors,
        "seconds_since_latest_success": min(success_ages) if success_ages else None,
        "seconds_since_latest_error": min(error_ages) if error_ages else None,
    }


def _dynamic_snapshot_source_ids(store: Any) -> tuple[list[str], bool]:
    root = getattr(store, "root", None)
    if root is None:
        return [], False
    try:
        directory = Path(root)
        if not directory.is_dir():
            return [], False
        source_ids: list[str] = []
        truncated = False
        for path in directory.glob(f"{_DYNAMIC_ARAM_SNAPSHOT_PREFIX}*.json"):
            name = path.name
            if name.startswith(".") or ".bad." in name or name.endswith(".status.json"):
                continue
            source_id = name[:-5]
            if not source_id.startswith(_DYNAMIC_ARAM_SNAPSHOT_PREFIX):
                continue
            source_ids.append(source_id)
            if len(source_ids) >= _MAX_DYNAMIC_SNAPSHOT_SCAN:
                truncated = True
                break
        return source_ids, truncated
    except Exception:
        return [], False


def _aggregate_aram_snapshots(store: Any) -> Dict[str, Any]:
    source_ids, truncated = _dynamic_snapshot_source_ids(store)
    max_age = aram_snapshot_max_age_seconds()
    status_counts: Dict[str, int] = {}
    available_count = 0
    ages: list[int] = []
    captured_values: list[str] = []
    errors: set[str] = set()
    for source_id in source_ids:
        item = _safe_snapshot(store, source_id, max_age)
        status = str(item.get("status") or "unavailable")
        status_counts[status] = status_counts.get(status, 0) + 1
        if item.get("available"):
            available_count += 1
            ages.append(_safe_non_negative_int(item.get("age_seconds")))
        captured_at = str(item.get("captured_at") or "")
        if captured_at:
            captured_values.append(captured_at)
        error_class = str(item.get("last_error_class") or "")
        if error_class:
            errors.add(error_class)
    return {
        "observed_count": len(source_ids),
        "available_count": available_count,
        "status_counts": dict(sorted(status_counts.items())),
        "newest_captured_at": max(captured_values) if captured_values else "",
        "newest_age_seconds": min(ages) if ages else 0,
        "oldest_age_seconds": max(ages) if ages else 0,
        "max_age_seconds": max_age,
        "last_error_classes": sorted(errors)[:_MAX_ERROR_CLASSES],
        "scan_truncated": truncated,
    }


def _aram_mode(
    *,
    cache_entries: int,
    augment: Mapping[str, Any],
    build: Mapping[str, Any],
    snapshots: Mapping[str, Any],
) -> str:
    if cache_entries > 0:
        return "cache"
    open_count = _safe_non_negative_int(augment.get("circuit_open_count")) + _safe_non_negative_int(
        build.get("circuit_open_count")
    )
    error_count = len(augment.get("last_error_classes") or []) + len(
        build.get("last_error_classes") or []
    )
    available = _safe_non_negative_int(snapshots.get("available_count"))
    success_seen = (
        augment.get("seconds_since_latest_success") is not None
        or build.get("seconds_since_latest_success") is not None
    )
    if open_count > 0:
        return "snapshot" if available > 0 else "unavailable"
    if error_count > 0:
        return "stale" if available > 0 else "unavailable"
    if success_seen:
        return "live"
    if available > 0:
        return "snapshot"
    return "unavailable"


def _safe_lolban(health_loader: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        raw = health_loader()
        health = raw if isinstance(raw, dict) else {}
    except Exception as exc:
        health = {
            "configured": False,
            "last_error_class": type(exc).__name__,
        }
    configured = bool(health.get("configured"))
    fresh = _safe_non_negative_int(health.get("fresh_cache_entries"))
    stale = _safe_non_negative_int(health.get("stale_cache_entries"))
    restored = _safe_non_negative_int(
        health.get("persistent_snapshot_restored_entries")
    )
    last_error_class = _safe_error_class(health.get("last_error_class"))
    if fresh > 0:
        mode = "cache"
    elif last_error_class and stale > 0:
        mode = "stale"
    elif str(health.get("last_success_at") or ""):
        mode = "live"
    elif restored > 0:
        mode = "snapshot"
    else:
        mode = "unavailable"
    return {
        "name": "lolban",
        "mode": mode,
        "configured": configured,
        "provider_count": _safe_non_negative_int(health.get("provider_count")),
        "fresh_cache_entries": fresh,
        "stale_cache_entries": stale,
        "last_success_at": str(health.get("last_success_at") or ""),
        "last_error_at": str(health.get("last_error_at") or ""),
        "last_error_class": last_error_class,
        "configuration_error_code": _safe_error_class(
            health.get("configuration_error_code")
        ),
        "configuration_error_class": _safe_error_class(
            health.get("configuration_error_class")
        ),
        "persistent_snapshot": {
            "enabled": bool(health.get("persistent_snapshot_enabled")),
            "status": _safe_error_class(
                health.get("persistent_snapshot_status")
            )
            or "disabled",
            "restored_entries": restored,
            "write_error_class": _safe_error_class(
                health.get("persistent_snapshot_write_error_class")
            ),
            "max_age_seconds": _safe_non_negative_int(STALE_CACHE_SECONDS),
        },
    }


def _overall_status(modes: Iterable[str]) -> tuple[str, Dict[str, int]]:
    counts: Dict[str, int] = {
        "live": 0,
        "cache": 0,
        "snapshot": 0,
        "stale": 0,
        "unavailable": 0,
    }
    for mode in modes:
        normalized = mode if mode in counts else "unavailable"
        counts[normalized] += 1
    if counts["unavailable"] == sum(counts.values()):
        status = "down"
    elif counts["unavailable"] or counts["stale"] or counts["snapshot"]:
        status = "degraded"
    else:
        status = "ok"
    return status, counts


def build_query_observability(
    ctx: Any,
    *,
    lolban_health_loader: Callable[[], Dict[str, Any]] = get_lolban_health,
) -> Dict[str, Any]:
    if ctx is None:
        return {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "generated_at": _utc_now_text(),
            "status": "down",
            "summary": {
                "live": 0,
                "cache": 0,
                "snapshot": 0,
                "stale": 0,
                "unavailable": 4,
            },
            "error_class": "context_unavailable",
            "sources": {},
            "caches": {},
        }

    states, monotonic_now = _client_state(ctx)
    store = getattr(ctx, "upstream_snapshot_store", None)
    shard_cache = getattr(ctx, "shard_cache", None)
    aram_cache = getattr(ctx, "aram_augment_cache", None)

    shard_data = _static_source(
        public_name="shard_data",
        source_id=SHARD_DATA_SOURCE_ID,
        cache_active=_cache_contains(shard_cache, "sources"),
        states=states,
        monotonic_now=monotonic_now,
        store=store,
        max_age_seconds=hero_snapshot_max_age_seconds(),
    )
    hero_catalog = _static_source(
        public_name="hero_catalog",
        source_id=SHARD_HERO_SOURCE_ID,
        cache_active=_cache_contains(aram_cache, "champion_catalog"),
        states=states,
        monotonic_now=monotonic_now,
        store=store,
        max_age_seconds=hero_snapshot_max_age_seconds(),
    )

    aram_augment = _aggregate_circuits(
        states,
        [_DYNAMIC_ARAM_AUGMENT_PREFIX],
        monotonic_now,
    )
    aram_build = _aggregate_circuits(
        states,
        [_DYNAMIC_ARAM_BUILD_PREFIX],
        monotonic_now,
    )
    aram_snapshots = _aggregate_aram_snapshots(store)
    aram_cache_entries = max(
        0,
        _cache_size(aram_cache)
        - (1 if _cache_contains(aram_cache, "champion_catalog") else 0),
    )
    aram = {
        "name": "aram",
        "mode": _aram_mode(
            cache_entries=aram_cache_entries,
            augment=aram_augment,
            build=aram_build,
            snapshots=aram_snapshots,
        ),
        "cache_entries": aram_cache_entries,
        "upstreams": {
            "augment_page": aram_augment,
            "build_page": aram_build,
        },
        "snapshots": aram_snapshots,
    }
    lolban = _safe_lolban(lolban_health_loader)

    sources = {
        "shard_data": shard_data,
        "hero_catalog": hero_catalog,
        "aram": aram,
        "lolban": lolban,
    }
    status, counts = _overall_status(
        str(source.get("mode") or "unavailable")
        for source in sources.values()
    )
    return {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "generated_at": _utc_now_text(),
        "status": status,
        "summary": counts,
        "sources": sources,
        "caches": {
            "shard_entries": _cache_size(shard_cache),
            "aram_payload_entries": aram_cache_entries,
            "aram_image_entries": _cache_size(
                getattr(ctx, "aram_image_cache", None)
            ),
        },
    }
