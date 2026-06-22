from typing import Any


def pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:.2f}".rstrip("0").rstrip(".") + "%"
