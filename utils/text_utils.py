from typing import Any


_EXACT_SEARCH_ALIASES = {
    "滑板鞋": "kalista",
}


def normalize_search_text(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "")
    return _EXACT_SEARCH_ALIASES.get(normalized, normalized)
