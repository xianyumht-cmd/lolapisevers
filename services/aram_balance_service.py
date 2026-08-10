from __future__ import annotations

import copy
import html
import re
import time
from typing import Any, Dict, List, Optional

from services.aram_augments_service import find_champion_for_opgg
from services.aram_upstream_state import (
    aram_snapshot_max_age_seconds,
    safe_error_class,
    safe_error_message,
    snapshot_store,
    upstream_client,
)


BALANCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_BALANCE_FIELDS = {
    "damage dealt": ("damage_dealt", "造成伤害"),
    "damage taken": ("damage_taken", "承受伤害"),
    "attack speed": ("attack_speed", "攻击速度"),
    "ability haste": ("ability_haste", "技能急速"),
    "cooldown reduction": ("ability_haste", "技能急速"),
    "healing": ("healing", "治疗"),
    "shielding": ("shielding", "护盾"),
    "tenacity": ("tenacity", "韧性"),
    "minion damage": ("minion_damage", "对小兵伤害"),
}
_BALANCE_PATTERN = re.compile(
    r"(?P<name>Damage\s+Dealt|Damage\s+Taken|Attack\s+Speed|Ability\s+Haste|"
    r"Cooldown\s+Reduction|Healing|Shielding|Tenacity|Minion\s+Damage)"
    r"\s*(?P<value>[+-]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
_PATCH_PATTERNS = (
    re.compile(r"Patch\s*:\s*(?P<patch>\d{1,2}\.\d{1,2})", re.IGNORECASE),
    re.compile(r"\bpatch\s*(?P<patch>\d{1,2}\.\d{1,2})\b", re.IGNORECASE),
)
_MULTIPLIER_KEYS = {
    "damage_dealt",
    "damage_taken",
    "attack_speed",
    "healing",
    "shielding",
    "minion_damage",
}


def _normalize_escaped_html(value: str) -> str:
    return (
        str(value or "")
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0026", "&")
        .replace('\\"', '"')
        .replace("\\/", "/")
    )


def _clean_text(value: str) -> str:
    text = _normalize_escaped_html(value)
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _patch_from_text(text: str) -> str:
    for pattern in _PATCH_PATTERNS:
        match = pattern.search(text)
        if match:
            return str(match.group("patch") or "").strip()
    return ""


def _numeric_value(raw: str) -> Optional[float]:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", str(raw or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _balance_direction(key: str, raw_value: str) -> str:
    numeric = _numeric_value(raw_value)
    if numeric is None:
        return "neutral"

    stripped = str(raw_value or "").strip()
    explicit_sign = stripped.startswith(("+", "-"))
    if explicit_sign:
        delta = numeric
    elif key in _MULTIPLIER_KEYS and stripped.endswith("%"):
        delta = numeric - 100.0
    else:
        delta = numeric

    if key == "damage_taken":
        delta = -delta
    if abs(delta) < 0.0001:
        return "neutral"
    return "buff" if delta > 0 else "debuff"


def parse_balance_page(value: str) -> Dict[str, Any]:
    text = _clean_text(value)
    changes: List[Dict[str, str]] = []
    seen = set()
    for match in _BALANCE_PATTERN.finditer(text):
        normalized_name = re.sub(r"\s+", " ", match.group("name").strip().lower())
        field = _BALANCE_FIELDS.get(normalized_name)
        if field is None:
            continue
        key, label = field
        raw_value = str(match.group("value") or "").strip()
        dedupe_key = (key, raw_value.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        changes.append(
            {
                "key": key,
                "label": label,
                "value": raw_value,
                "direction": _balance_direction(key, raw_value),
            }
        )
        if len(changes) >= 10:
            break

    return {
        "patch": _patch_from_text(text),
        "changes": changes,
        "summary": " · ".join(
            f"{item['label']} {item['value']}" for item in changes
        ),
    }


def _camel_slug(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    text = text.replace("'", "").replace(".", "").replace("_", "-").replace(" ", "-")
    text = re.sub(r"-+", "-", text)
    return text.strip("-").lower()


def _slug_candidates(hero: Dict[str, Any]) -> List[str]:
    values: List[str] = []

    def add(raw: Any) -> None:
        slug = str(raw or "").strip().lower()
        if slug and slug not in values:
            values.append(slug)

    alias = str(hero.get("alias") or "").strip()
    add(hero.get("slug"))
    add(alias)
    add(_camel_slug(alias))

    if alias.casefold() == "monkeyking":
        values = [value for value in values if value != "wukong"]
        values.insert(0, "wukong")
    return values


def _empty_balance(*, error_class: str = "", status: str = "unavailable") -> Dict[str, Any]:
    return {
        "status": status,
        "provider": "arammayhem",
        "patch": "",
        "changes": [],
        "summary": "",
        "stale": False,
        "snapshot_age_seconds": 0,
        "error_class": str(error_class or ""),
        "duration_ms": 0.0,
        "attempts": 0,
        "http_status": 0,
    }


def _fetch_balance(ctx: Any, hero: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    alias = str(hero.get("alias") or hero.get("name") or "unknown").strip().casefold()
    source_id = "aram-balance-" + re.sub(r"[^a-z0-9_.-]+", "-", alias).strip("-")
    if not source_id or source_id == "aram-balance-":
        source_id = "aram-balance-unknown"

    store = snapshot_store(ctx)
    snapshot = store.load(source_id, max_age_seconds=aram_snapshot_max_age_seconds())
    last_error_class = "unavailable"
    last_error_message = ""
    attempts = 0
    http_status = 0

    for slug in _slug_candidates(hero):
        response = upstream_client(ctx).request(
            source_id,
            f"https://arammayhem.com/build/{slug}/",
            headers=BALANCE_HEADERS,
            attempts=1,
            connect_timeout=2.0,
            read_timeout=4.0,
        )
        attempts = max(attempts, int(response.attempts or 0))
        http_status = int(response.status_code or 0)
        if not response.ok:
            last_error_class = safe_error_class(response)
            last_error_message = safe_error_message(response)
            continue

        parsed = parse_balance_page(response.text)
        if not parsed.get("patch") and not parsed.get("changes"):
            last_error_class = "validation_error"
            last_error_message = "balance page contained no recognizable patch or adjustment data"
            continue

        result = {
            **_empty_balance(status="ok"),
            **parsed,
            "status": "ok",
            "stale": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "attempts": int(response.attempts or 0),
            "http_status": int(response.status_code or 0),
            "error_class": "",
        }
        try:
            store.save(
                source_id,
                result,
                {
                    "provider": "arammayhem",
                    "patch": str(result.get("patch") or ""),
                    "http_status": int(response.status_code or 0),
                },
            )
        except Exception:
            pass
        return result

    if snapshot.ok and isinstance(snapshot.payload, dict):
        result = copy.deepcopy(snapshot.payload)
        result["status"] = "snapshot"
        result["stale"] = True
        result["snapshot_age_seconds"] = int(snapshot.age_seconds)
        result["error_class"] = last_error_class
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["attempts"] = attempts
        result["http_status"] = http_status
        return result

    try:
        store.record_refresh_error(source_id, last_error_class, last_error_message)
    except Exception:
        pass
    result = _empty_balance(error_class=last_error_class)
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["attempts"] = attempts
    result["http_status"] = http_status
    return result


def query_aram_balance(ctx: Any, hero_query: str) -> Dict[str, Any]:
    hero = find_champion_for_opgg(ctx, hero_query)
    if not hero:
        return _empty_balance(error_class="hero_not_found")

    alias = str(hero.get("alias") or hero.get("name") or "unknown").strip().casefold()
    cache_key = f"aram_balance:{alias}"
    cached = ctx.aram_augment_cache.get(cache_key)
    if isinstance(cached, dict):
        result = copy.deepcopy(cached)
        result["cache_hit"] = True
        return result

    result = _fetch_balance(ctx, hero)
    cached_result = copy.deepcopy(result)
    cached_result["cache_hit"] = False
    ctx.aram_augment_cache.set(cache_key, cached_result)
    return copy.deepcopy(cached_result)
