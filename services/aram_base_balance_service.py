from __future__ import annotations

import copy
import html
import re
import time
from typing import Any, Dict, List, Optional

from services.aram_balance_service import (
    _balance_direction,
    _current_riot_patch,
    _patches_match,
    _riot_display_patch,
    _slug_candidates,
    find_champion_for_balance,
)
from services.aram_upstream_state import (
    aram_snapshot_max_age_seconds,
    safe_error_class,
    safe_error_message,
    snapshot_store,
    upstream_client,
)


BASE_BALANCE_HTTP_SOURCE_ID = "aram-base-balance-page"
BASE_BALANCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.7,zh;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://op.gg/lol/modes/aram",
}

_BASE_FIELDS = (
    (
        "damage_dealt",
        "造成伤害",
        ("Damage Dealt", "造成伤害"),
    ),
    (
        "damage_taken",
        "承受伤害",
        ("Damage Taken", "Damage Received", "承受伤害", "受到伤害", "承伤"),
    ),
    (
        "attack_speed",
        "攻击速度",
        ("Attack Speed", "攻击速度", "攻速"),
    ),
    (
        "ability_haste",
        "技能急速",
        (
            "Ability Haste",
            "Cooldown Reduction",
            "技能急速",
            "技能加速",
            "冷却缩减",
        ),
    ),
    (
        "healing",
        "治疗",
        ("Healing", "Healing Done", "治疗效果", "治疗", "生命恢复"),
    ),
    (
        "shielding",
        "护盾",
        (
            "Shield Amount",
            "Shielding",
            "护盾吸收量",
            "护盾效果",
            "护盾量",
            "护盾",
        ),
    ),
    (
        "tenacity",
        "韧性",
        ("Tenacity", "韧性"),
    ),
    (
        "minion_damage",
        "对小兵伤害",
        (
            "Damage Dealt to Minions",
            "Damage to Minions",
            "Minion Damage",
            "对小兵伤害",
            "小兵伤害",
        ),
    ),
    (
        "resource_regen",
        "资源回复",
        (
            "Energy Regen",
            "Energy Regeneration",
            "Mana Regen",
            "Mana Regeneration",
            "能量回复",
            "能量恢复",
            "法力回复",
            "法力恢复",
        ),
    ),
)

_SECTION_MARKERS = (
    "Balance adjustment",
    "Balance Adjustment",
    "平衡调整",
    "平衡性调整",
)
_END_MARKERS = (
    "Summoner spells",
    "Summoner Spells",
    "召唤师技能",
    "Build",
    "出装",
    "Runes",
    "符文",
)
_PATCH_PATTERNS = (
    re.compile(r"\bPatch\s*:?\s*(?P<patch>\d{1,2}\.\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bVer(?:sion)?\s*:\s*(?P<patch>\d{1,2}\.\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(?P<patch>\d{1,2}\.\d{1,2})\s*版本\b", re.IGNORECASE),
    re.compile(r"版本(?:号)?\s*[:：]?\s*(?P<patch>\d{1,2}\.\d{1,2})\b", re.IGNORECASE),
)
_SIGNED_MODIFIER_RE = re.compile(r"(?<![\d.])[+-]\s*\d+(?:\.\d+)?%?")


def _clean_visible_text(value: str) -> str:
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
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _extract_patch(text: str) -> str:
    for pattern in _PATCH_PATTERNS:
        match = pattern.search(text)
        if match:
            return str(match.group("patch") or "").strip()
    return ""


def _extract_section(text: str) -> str:
    lowered = text.casefold()
    starts = [
        lowered.find(marker.casefold())
        for marker in _SECTION_MARKERS
        if lowered.find(marker.casefold()) >= 0
    ]
    if not starts:
        return ""
    start = min(starts)
    section = text[start : start + 2200]
    section_lower = section.casefold()
    ends: List[int] = []
    for marker in _END_MARKERS:
        index = section_lower.find(marker.casefold(), 24)
        if index > 0:
            ends.append(index)
    if ends:
        section = section[: min(ends)]
    return section.strip()


def _numeric_value(value: str) -> Optional[float]:
    match = re.search(r"[+-]?\s*\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(re.sub(r"\s+", "", match.group(0)))
    except ValueError:
        return None


def _base_patch_matches_current(page_patch: str, current_patch: str) -> bool:
    if not page_patch or not current_patch:
        return False
    if _patches_match(page_patch, current_patch):
        return True
    mapped = _riot_display_patch(page_patch)
    return bool(mapped and _patches_match(mapped, current_patch))


def parse_base_balance_page(value: str) -> Dict[str, Any]:
    text = _clean_visible_text(value)
    page_patch = _extract_patch(text)
    section = _extract_section(text)
    if not section:
        return {
            "complete": False,
            "patch": page_patch,
            "changes": [],
            "summary": "",
            "error_class": "balance_section_missing",
        }

    changes: List[Dict[str, str]] = []
    recognized_signed_count = 0
    for key, label, aliases in _BASE_FIELDS:
        alias_pattern = "|".join(
            re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)
        )
        match = re.search(
            rf"(?:{alias_pattern})\s*[:：]?\s*(?P<value>(?:[+-]\s*)?\d+(?:\.\d+)?%?|-)",
            section,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        raw_value = str(match.group("value") or "").strip()
        raw_value = re.sub(r"^([+-])\s+", r"\1", raw_value)
        numeric = _numeric_value(raw_value)
        if len(raw_value) > 1 and raw_value[0] in "+-" and numeric is not None:
            recognized_signed_count += 1
        if raw_value == "-" or (numeric is not None and abs(numeric) < 0.0001):
            continue
        changes.append(
            {
                "key": key,
                "label": label,
                "value": raw_value,
                "direction": _balance_direction(key, raw_value),
            }
        )

    # The balance card can contain unrelated unsigned page statistics or ad text.
    # Only unrecognized signed +X/-X values are strong evidence that OP.GG added a
    # balance modifier field we do not understand yet. Keep those fail-closed while
    # allowing harmless unsigned numbers to coexist with the card.
    signed_tokens = _SIGNED_MODIFIER_RE.findall(section)
    if len(signed_tokens) > recognized_signed_count:
        return {
            "complete": False,
            "patch": page_patch,
            "changes": changes,
            "summary": "",
            "error_class": "unparsed_balance_values",
        }

    return {
        "complete": True,
        "patch": page_patch,
        "changes": changes,
        "summary": (
            " · ".join(f"{item['label']} {item['value']}" for item in changes)
            if changes
            else "当前无英雄专属基础平衡修正"
        ),
        "error_class": "",
    }


def _empty_base(*, error_class: str = "", status: str = "unavailable") -> Dict[str, Any]:
    return {
        "status": status,
        "provider": "opgg",
        "scope": "aram_base",
        "patch": "",
        "display_patch": "",
        "current_patch_verified": False,
        "complete": False,
        "changes": [],
        "summary": "",
        "stale": False,
        "snapshot_age_seconds": 0,
        "error_class": str(error_class or ""),
        "duration_ms": 0.0,
        "attempts": 0,
        "http_status": 0,
    }


def _syncing_base(
    *,
    official_patch: str,
    page_patch: str,
    started: float,
    attempts: int,
    http_status: int,
) -> Dict[str, Any]:
    result = _empty_base(error_class="patch_mismatch", status="syncing")
    result.update(
        {
            "patch": page_patch,
            "display_patch": _riot_display_patch(page_patch) or page_patch,
            "current_patch_verified": True,
            "summary": (
                f"当前版本 {official_patch}，基础平衡页仍为 "
                f"{page_patch or '未知旧版本'}，旧完整数值已隐藏。"
            ),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "attempts": attempts,
            "http_status": http_status,
        }
    )
    return result


def _snapshot_source_id(alias: str) -> str:
    safe = re.sub(r"[^a-z0-9_.-]+", "-", alias.casefold()).strip("-")
    return f"aram-base-balance-{safe or 'unknown'}"


def _fetch_base_balance(ctx: Any, hero: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    alias = str(hero.get("alias") or hero.get("name") or "unknown").strip()
    source_id = _snapshot_source_id(alias)
    store = snapshot_store(ctx)
    snapshot = store.load(
        source_id,
        max_age_seconds=aram_snapshot_max_age_seconds(),
    )
    official_patch = _current_riot_patch(ctx)
    last_error_class = "unavailable"
    last_error_message = ""
    attempts = 0
    http_status = 0

    for slug in _slug_candidates(hero):
        response = upstream_client(ctx).request(
            BASE_BALANCE_HTTP_SOURCE_ID,
            f"https://op.gg/lol/modes/aram/{slug}/build",
            headers=BASE_BALANCE_HEADERS,
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

        parsed = parse_base_balance_page(response.text)
        page_patch = str(parsed.get("patch") or "").strip()
        if not parsed.get("complete"):
            last_error_class = str(parsed.get("error_class") or "validation_error")
            last_error_message = "base balance page was incomplete"
            continue

        if official_patch and page_patch and not _base_patch_matches_current(page_patch, official_patch):
            return _syncing_base(
                official_patch=official_patch,
                page_patch=page_patch,
                started=started,
                attempts=int(response.attempts or 0),
                http_status=int(response.status_code or 0),
            )

        status = "ok" if parsed.get("changes") else "none"
        verified = bool(
            official_patch and page_patch and _base_patch_matches_current(page_patch, official_patch)
        )
        if not page_patch:
            status = "unverified"
        result = {
            **_empty_base(status=status),
            **parsed,
            "status": status,
            "provider": "opgg",
            "scope": "aram_base",
            "patch": page_patch,
            "display_patch": _riot_display_patch(page_patch) or page_patch,
            "current_patch_verified": verified,
            "complete": True,
            "stale": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "attempts": int(response.attempts or 0),
            "http_status": int(response.status_code or 0),
            "error_class": "" if page_patch else "patch_unverified",
        }
        try:
            store.save(
                source_id,
                result,
                {
                    "provider": "opgg",
                    "scope": "aram_base",
                    "patch": page_patch,
                    "display_patch": str(result.get("display_patch") or ""),
                    "current_patch_verified": verified,
                    "http_status": int(response.status_code or 0),
                },
            )
        except Exception:
            pass
        return result

    if snapshot.ok and isinstance(snapshot.payload, dict):
        snapshot_patch = str(snapshot.payload.get("patch") or "").strip()
        if official_patch and (
            not snapshot_patch
            or not _base_patch_matches_current(snapshot_patch, official_patch)
        ):
            return _syncing_base(
                official_patch=official_patch,
                page_patch=snapshot_patch,
                started=started,
                attempts=attempts,
                http_status=http_status,
            )
        result = copy.deepcopy(snapshot.payload)
        result["status"] = "snapshot"
        result["stale"] = True
        result["snapshot_age_seconds"] = int(snapshot.age_seconds)
        result["current_patch_verified"] = bool(
            official_patch
            and snapshot_patch
            and _base_patch_matches_current(snapshot_patch, official_patch)
        )
        result["error_class"] = last_error_class
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["attempts"] = attempts
        result["http_status"] = http_status
        return result

    try:
        store.record_refresh_error(source_id, last_error_class, last_error_message)
    except Exception:
        pass
    result = _empty_base(error_class=last_error_class)
    result["display_patch"] = official_patch
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["attempts"] = attempts
    result["http_status"] = http_status
    return result


def query_aram_base_balance(ctx: Any, hero_query: str) -> Dict[str, Any]:
    hero = find_champion_for_balance(ctx, hero_query)
    if not hero:
        return _empty_base(error_class="hero_not_found")

    alias = str(hero.get("alias") or hero.get("name") or "unknown").strip().casefold()
    cache_key = f"aram_base_balance:{alias}"
    cached = ctx.aram_augment_cache.get(cache_key)
    if isinstance(cached, dict):
        result = copy.deepcopy(cached)
        result["cache_hit"] = True
        return result

    result = _fetch_base_balance(ctx, hero)
    cached_result = copy.deepcopy(result)
    cached_result["cache_hit"] = False
    ctx.aram_augment_cache.set(cache_key, cached_result)
    return copy.deepcopy(cached_result)
