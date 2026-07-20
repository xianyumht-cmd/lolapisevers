from __future__ import annotations

import os
from typing import Any

from . import management


_EXTRA_MAIN_FIELDS: list[dict[str, Any]] = [
    {
        "key": "SHARD_DATA_URL",
        "label": "云顶合集数据源 URL",
        "section": "数据源",
        "type": "text",
    },
    {
        "key": "SHARD_HERO_URL",
        "label": "英雄列表数据源 URL",
        "section": "数据源",
        "type": "text",
    },
    {
        "key": "WEBUI_ADMIN_TOKEN",
        "label": "WebUI 管理令牌",
        "section": "控制台安全",
        "type": "secret",
    },
]

_LANZOU_OVERRIDE_KEYS = [
    "LANZOU_STATE_PATH",
    "LANZOU_MONITOR_HOST",
    "LANZOU_MONITOR_PORT",
    "LANZOU_SCAN_INTERVAL_SECONDS",
    "LANZOU_SCAN_BATCH_SIZE",
    "LANZOU_SCAN_BATCH_PAUSE_SECONDS",
    "LANZOU_API_KEY",
    "LANZOU_WATCH_URLS",
]


def _ensure_main_fields() -> None:
    for field in _EXTRA_MAIN_FIELDS:
        key = field["key"]
        if key in management._FIELD_BY_KEY:
            continue
        management.MAIN_CONFIG_FIELDS.append(field)
        management._FIELD_BY_KEY[key] = field


def read_main_config() -> dict[str, Any]:
    _ensure_main_fields()
    return management.read_main_config()


def update_main_config(patch: dict[str, Any]) -> dict[str, Any]:
    _ensure_main_fields()
    return management.update_main_config(patch)


def lanzou_environment_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    for key in _LANZOU_OVERRIDE_KEYS:
        value = os.getenv(key)
        if value is None or not value.strip():
            continue
        overrides[key] = "已配置" if key == "LANZOU_API_KEY" else value
    return overrides
