from typing import Any


def normalize_search_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")
