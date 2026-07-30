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
        "key": "IMAGE_ASSET_DISK_CACHE_ENABLED",
        "label": "图片文件缓存启用",
        "section": "图片资源缓存",
        "type": "bool",
    },
    {
        "key": "IMAGE_ASSET_CACHE_DIR",
        "label": "图片缓存目录（留空使用 data/image-cache）",
        "section": "图片资源缓存",
        "type": "text",
    },
    {
        "key": "IMAGE_ASSET_CACHE_TTL_DAYS",
        "label": "图片缓存天数（0=长期）",
        "section": "图片资源缓存",
        "type": "int",
        "min": 0,
        "max": 36500,
    },
    {
        "key": "IMAGE_ASSET_SYNC_WORKERS",
        "label": "批量下载并发数",
        "section": "图片资源缓存",
        "type": "int",
        "min": 1,
        "max": 32,
    },
    {
        "key": "IMAGE_ASSET_SYNC_TIMEOUT_SECONDS",
        "label": "单张图片下载超时秒数",
        "section": "图片资源缓存",
        "type": "int",
        "min": 1,
        "max": 60,
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

_REQUIRED_TEXT_KEYS = {"APP_HOST", "MYSQL_HOST"}


def _ensure_main_fields() -> None:
    for field in _EXTRA_MAIN_FIELDS:
        key = field["key"]
        if key in management._FIELD_BY_KEY:
            continue
        management.MAIN_CONFIG_FIELDS.append(field)
        management._FIELD_BY_KEY[key] = field


def _read_example_values() -> dict[str, str]:
    path = management.APP_ENV_EXAMPLE_PATH
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    return management._parse_env_values(text)


def _apply_missing_example_values(result: dict[str, Any]) -> dict[str, Any]:
    source_text, _source = management._read_env_source()
    source_values = management._parse_env_values(source_text)
    example_values = _read_example_values()

    for item in result.get("fields", []):
        key = str(item.get("key") or "")
        if not key or key in source_values or os.getenv(key) is not None:
            continue
        if key not in example_values:
            continue
        fallback = example_values[key]
        field_type = item.get("type")
        if field_type == "secret":
            item["configured"] = bool(fallback.strip() and fallback.strip() != "CHANGE_ME")
        elif field_type == "bool":
            item["value"] = fallback.strip().lower() not in {"0", "false", "no", "off", ""}
        else:
            item["value"] = fallback
        item["inherited_from_example"] = True
    return result


def read_main_config() -> dict[str, Any]:
    _ensure_main_fields()
    return _apply_missing_example_values(management.read_main_config())


def _validate_patch_values(patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        spec = management._FIELD_BY_KEY.get(key)
        if spec is None or spec.get("type") == "secret":
            continue
        try:
            management._normalize_main_value(spec, value)
        except (TypeError, ValueError) as exc:
            message = str(exc)
            if key in message:
                raise
            raise ValueError(f"{key}: {message}") from exc


def update_main_config(patch: dict[str, Any]) -> dict[str, Any]:
    _ensure_main_fields()
    if not isinstance(patch, dict):
        raise ValueError("main config patch must be an object")

    effective_fields = {
        str(item.get("key") or ""): item
        for item in read_main_config().get("fields", [])
        if item.get("key")
    }
    normalized_patch = dict(patch)
    for key, value in patch.items():
        spec = management._FIELD_BY_KEY.get(key)
        if spec is None or spec.get("type") == "secret":
            continue
        is_blank = value is None or str(value).strip() == ""
        needs_value = spec.get("type") == "int" or key in _REQUIRED_TEXT_KEYS
        if not is_blank or not needs_value:
            continue
        fallback = effective_fields.get(key, {}).get("value")
        if fallback is not None and str(fallback).strip() != "":
            normalized_patch[key] = fallback

    _validate_patch_values(normalized_patch)
    return management.update_main_config(normalized_patch)


def lanzou_environment_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    for key in _LANZOU_OVERRIDE_KEYS:
        value = os.getenv(key)
        if value is None or not value.strip():
            continue
        overrides[key] = "已配置" if key == "LANZOU_API_KEY" else value
    return overrides
