from datetime import datetime
from typing import Any

from utils.convert import safe_int


def format_ts_ms(ts_ms: Any) -> str:
    if ts_ms is None:
        return ""
    try:
        ts = float(ts_ms) / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def format_duration(seconds: Any) -> str:
    total = safe_int(seconds)
    if total <= 0:
        return "-"
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"
