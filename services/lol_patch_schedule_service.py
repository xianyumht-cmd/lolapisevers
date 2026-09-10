from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Any


SCHEDULE_TIMEZONE = "Asia/Shanghai"
SHANGHAI_TZ = timezone(timedelta(hours=8), name=SCHEDULE_TIMEZONE)
RIOT_PATCH_SCHEDULE_URL = (
    "https://support-leagueoflegends.riotgames.com/hc/en-us/articles/"
    "360018987893-Patch-Schedule-League-of-Legends"
)
SCHEDULE_SOURCE = "riot_patch_schedule_snapshot_2026"

# Verified against Riot's official 2026 League of Legends patch schedule.
# Riot notes that scheduled dates can change, so this snapshot is intentionally
# isolated in one service and can be refreshed without changing API consumers.
PATCH_SCHEDULE_2026: tuple[tuple[Date, str], ...] = (
    (Date(2026, 1, 8), "26.01"),
    (Date(2026, 1, 22), "26.02"),
    (Date(2026, 2, 4), "26.03"),
    (Date(2026, 2, 19), "26.04"),
    (Date(2026, 3, 4), "26.05"),
    (Date(2026, 3, 18), "26.06"),
    (Date(2026, 4, 1), "26.07"),
    (Date(2026, 4, 15), "26.08"),
    (Date(2026, 4, 29), "26.09"),
    (Date(2026, 5, 13), "26.10"),
    (Date(2026, 5, 28), "26.11"),
    (Date(2026, 6, 10), "26.12"),
    (Date(2026, 6, 24), "26.13"),
    (Date(2026, 7, 15), "26.14"),
    (Date(2026, 7, 29), "26.15"),
    (Date(2026, 8, 12), "26.16"),
    (Date(2026, 8, 26), "26.17"),
    (Date(2026, 9, 10), "26.18"),
    (Date(2026, 9, 23), "26.19"),
    (Date(2026, 10, 7), "26.20"),
    (Date(2026, 10, 21), "26.21"),
    (Date(2026, 11, 4), "26.22"),
    (Date(2026, 11, 18), "26.23"),
    (Date(2026, 12, 9), "26.24"),
)


def _parse_requested_date(value: str) -> Date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("invalid_date")
    try:
        parsed = Date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_date") from exc
    if parsed.isoformat() != text:
        raise ValueError("invalid_date")
    return parsed


def _shanghai_now(now: datetime | None = None) -> datetime:
    # Mainland China uses UTC+08 year-round. A fixed offset keeps this endpoint
    # deterministic on Windows hosts that do not ship the IANA tzdata database.
    if now is None:
        return datetime.now(SHANGHAI_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI_TZ)
    return now.astimezone(SHANGHAI_TZ)


def get_patch_status(
    date_text: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = _shanghai_now(now)
    requested_date = (
        _parse_requested_date(date_text)
        if date_text is not None
        else checked_at.date()
    )

    current_patch: str | None = None
    exact_patch: str | None = None
    next_date: Date | None = None
    next_patch: str | None = None

    for patch_date, patch in PATCH_SCHEDULE_2026:
        if patch_date <= requested_date:
            current_patch = patch
        if patch_date == requested_date:
            exact_patch = patch
        if patch_date > requested_date:
            next_date = patch_date
            next_patch = patch
            break

    is_update_today = exact_patch is not None
    event_id = (
        f"lol-patch-{exact_patch}-{requested_date.isoformat()}"
        if exact_patch is not None
        else None
    )

    return {
        "date": requested_date.isoformat(),
        "patch": exact_patch or current_patch,
        "is_update_today": is_update_today,
        "next_update_date": next_date.isoformat() if next_date else None,
        "next_patch": next_patch,
        "source": SCHEDULE_SOURCE,
        "source_url": RIOT_PATCH_SCHEDULE_URL,
        "checked_at": checked_at.isoformat(),
        "event_id": event_id,
        "schedule_timezone": SCHEDULE_TIMEZONE,
    }
