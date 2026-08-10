from __future__ import annotations

import asyncio
import copy
import html
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.aram_augments_service import find_champion_for_opgg
from services.aram_upstream_state import (
    request_opgg_html,
    safe_error_class,
    safe_error_message,
    safe_source_suffix,
    snapshot_store,
)


_BALANCE_RULES = (
    (
        "damage_dealt",
        "造成伤害",
        ("Damage Dealt", "造成伤害"),
        False,
    ),
    (
        "damage_taken",
        "承受伤害",
        ("Damage Taken", "Damage Received", "承受伤害", "受到伤害"),
        True,
    ),
    (
        "attack_speed",
        "攻击速度",
        ("Attack Speed", "攻击速度"),
        False,
    ),
    (
        "ability_haste",
        "技能急速",
        (
            "Ability Haste",
            "Cooldown Reduction",
            "技能急速",
            "冷却缩减",
        ),
        False,
    ),
    (
        "healing",
        "治疗",
        ("Healing", "治疗效果", "治疗"),
        False,
    ),
    (
        "shielding",
        "护盾",
        ("Shield Amount", "Shielding", "护盾效果", "护盾量", "护盾"),
        False,
    ),
    (
        "tenacity",
        "韧性",
        ("Tenacity", "韧性"),
        False,
    ),
    (
        "minion_damage",
        "对小兵伤害",
        ("Damage Dealt to Minions", "Minion Damage", "对小兵伤害"),
        False,
    ),
)

_BALANCE_SECTION_MARKERS = (
    "Balance adjustment",
    "Balance Adjustment",
    "平衡调整",
    "平衡性调整",
)
_BALANCE_END_MARKERS = (
    "Summoner spells",
    "Summoner Spells",
    "召唤师技能",
    "Build",
    "出装",
    "Runes",
    "符文",
)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _snapshot_max_age_seconds() -> int:
    return _env_int(
        "ARAM_BALANCE_SNAPSHOT_MAX_AGE_SECONDS",
        14 * 24 * 60 * 60,
        60,
        60 * 24 * 60 * 60,
    )


def _source_id(alias: str) -> str:
    return f"aram-balance-{safe_source_suffix(alias.casefold())}"[:128]


def _slug_candidates(hero: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for value in (hero.get("slug"), hero.get("alias")):
        slug = str(value or "").strip().lower()
        if slug and slug not in candidates:
            candidates.append(slug)
    if str(hero.get("alias") or "").casefold() == "monkeyking":
        if "wukong" not in candidates:
            candidates.insert(0, "wukong")
    return candidates


def _normalize_visible_text(value: str) -> str:
    text = str(value or "")
    text = (
        text.replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace('\\"', '"')
        .replace("\\n", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("−", "-")
    )
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_balance_section(text: str) -> str:
    lowered = text.casefold()
    starts = [
        lowered.find(marker.casefold())
        for marker in _BALANCE_SECTION_MARKERS
        if lowered.find(marker.casefold()) >= 0
    ]
    if not starts:
        return ""
    start = min(starts)
    section = text[start : start + 1800]
    section_lower = section.casefold()
    ends = []
    for marker in _BALANCE_END_MARKERS:
        index = section_lower.find(marker.casefold(), 24)
        if index > 0:
            ends.append(index)
    if ends:
        section = section[: min(ends)]
    return section.strip()


def _parse_patch(text: str) -> str:
    for pattern in (
        r"\bPatch\s*:?\s*(\d{1,2}\.\d{1,2})\b",
        r"\b(\d{1,2}\.\d{1,2})\s*版本\b",
    ):
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1)
    return ""


def _numeric_value(value: str) -> Optional[float]:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _direction(key: str, value: str, inverse: bool) -> str:
    numeric = _numeric_value(value)
    if numeric is None or numeric == 0:
        return "neutral"
    positive_is_debuff = inverse or key == "damage_taken"
    if numeric > 0:
        return "debuff" if positive_is_debuff else "buff"
    return "buff" if positive_is_debuff else "debuff"


def extract_aram_balance_state(html_text: str) -> Dict[str, Any]:
    visible = _normalize_visible_text(html_text)
    section = _extract_balance_section(visible)
    if not section:
        return {
            "status": "unavailable",
            "complete": False,
            "patch": _parse_patch(visible),
            "items": [],
            "buffs": [],
            "debuffs": [],
            "summary": "平衡数据暂不可用",
            "error_class": "balance_section_missing",
        }

    items: List[Dict[str, str]] = []
    for key, label, aliases, inverse in _BALANCE_RULES:
        alias_pattern = "|".join(
            re.escape(alias)
            for alias in sorted(aliases, key=len, reverse=True)
        )
        match = re.search(
            rf"(?:{alias_pattern})\s*[:：]?\s*(?P<value>-|[+-]?\d+(?:\.\d+)?%?)",
            section,
            flags=re.I,
        )
        if not match:
            continue
        value = match.group("value").strip()
        numeric = _numeric_value(value)
        if value == "-" or numeric == 0:
            continue
        direction = _direction(key, value, inverse)
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "direction": direction,
            }
        )

    buffs = [copy.deepcopy(item) for item in items if item["direction"] == "buff"]
    debuffs = [
        copy.deepcopy(item) for item in items if item["direction"] == "debuff"
    ]
    status = "ok" if items else "none"
    summary = (
        " · ".join(f"{item['label']} {item['value']}" for item in items)
        if items
        else "当前无英雄专属平衡修正"
    )
    return {
        "status": status,
        "complete": True,
        "patch": _parse_patch(visible),
        "items": items,
        "buffs": buffs,
        "debuffs": debuffs,
        "summary": summary,
        "error_class": "",
    }


def _snapshot_fallback(
    snapshot: Any,
    *,
    error_class: str,
    source_url: str = "",
) -> Dict[str, Any]:
    if getattr(snapshot, "ok", False) and isinstance(snapshot.payload, dict):
        result = copy.deepcopy(snapshot.payload)
        result["status"] = "snapshot"
        result["stale"] = True
        result["snapshot_age_seconds"] = int(snapshot.age_seconds)
        result["fallback_reason"] = error_class
        result["error_class"] = error_class
        return result
    return {
        "status": "unavailable",
        "complete": False,
        "scope": "aram",
        "provider": "opgg",
        "source_url": source_url,
        "patch": "",
        "items": [],
        "buffs": [],
        "debuffs": [],
        "summary": "平衡数据暂不可用（不等于无修正）",
        "stale": False,
        "snapshot_age_seconds": 0,
        "fallback_reason": error_class,
        "error_class": error_class,
    }


def build_aram_balance_payload(
    ctx: Any,
    query: str,
    *,
    resolved_hero: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    hero = resolved_hero or find_champion_for_opgg(ctx, query)
    if not hero:
        return _snapshot_fallback(
            type("MissingSnapshot", (), {"ok": False})(),
            error_class="champion_not_found",
        )

    alias = str(hero.get("alias") or "").strip()
    if not alias:
        return _snapshot_fallback(
            type("MissingSnapshot", (), {"ok": False})(),
            error_class="champion_alias_missing",
        )

    cache_key = f"aram_balance:{alias.casefold()}"
    cached = ctx.aram_augment_cache.get(cache_key)
    if isinstance(cached, dict):
        result = copy.deepcopy(cached)
        result["cache_hit"] = True
        return result

    store = snapshot_store(ctx)
    source_id = _source_id(alias)
    snapshot = store.load(
        source_id,
        max_age_seconds=_snapshot_max_age_seconds(),
    )
    last_error = "unavailable"
    last_url = ""

    for slug in _slug_candidates(hero):
        url = f"https://op.gg/zh-cn/lol/modes/aram/{slug}/build"
        last_url = url
        response = request_opgg_html(
            ctx,
            page_kind="balance",
            slug=slug,
            url=url,
            attempts=1,
            connect_timeout=2.0,
            read_timeout=4.0,
        )
        if not response.ok:
            last_error = safe_error_class(response)
            try:
                store.record_refresh_error(
                    source_id,
                    last_error,
                    safe_error_message(response),
                )
            except Exception:
                pass
            continue

        parsed = extract_aram_balance_state(response.text)
        if not parsed.get("complete"):
            last_error = str(parsed.get("error_class") or "validation_error")
            try:
                store.record_refresh_error(source_id, last_error, "")
            except Exception:
                pass
            continue

        result = {
            **parsed,
            "scope": "aram",
            "provider": "opgg",
            "source_url": url,
            "stale": False,
            "snapshot_age_seconds": 0,
            "fallback_reason": "",
            "cache_hit": False,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        try:
            store.save(
                source_id,
                result,
                {
                    "http_status": int(response.status_code or 0),
                    "upstream_status": str(response.status or ""),
                    "source_url": url,
                },
            )
        except Exception:
            pass
        ctx.aram_augment_cache.set(cache_key, copy.deepcopy(result))
        return result

    result = _snapshot_fallback(
        snapshot,
        error_class=last_error,
        source_url=last_url,
    )
    result["cache_hit"] = False
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    ctx.aram_augment_cache.set(cache_key, copy.deepcopy(result))
    return result


async def query_aram_balance(ctx: Any, *, hero: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(build_aram_balance_payload, ctx, hero)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {
            "status": "unavailable",
            "complete": False,
            "scope": "aram",
            "provider": "opgg",
            "source_url": "",
            "patch": "",
            "items": [],
            "buffs": [],
            "debuffs": [],
            "summary": "平衡数据暂不可用（不等于无修正）",
            "stale": False,
            "snapshot_age_seconds": 0,
            "fallback_reason": exc.__class__.__name__,
            "error_class": exc.__class__.__name__,
            "cache_hit": False,
        }
