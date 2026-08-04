from __future__ import annotations

import copy
from typing import Any, Mapping

from .parser_center_admin import _load_effective_config, save_parser_center


_MIGRATION_ID = "lolban-backup-presets-v2"

_STANDARD_LOLBAN_PARSER: dict[str, Any] = {
    "success": {"path": "code", "op": "eq", "value": 200},
    "error_message_paths": ["msg", "message", "error"],
    "outcomes": [
        {
            "name": "hit",
            "when": {"path": "data.status", "op": "eq", "value": "封禁"},
        },
        {
            "name": "clear",
            "when": {"path": "data.status", "op": "eq", "value": "正常"},
        },
    ],
    "default_outcome": "unknown",
    "fields": {
        "qq": {
            "paths": ["data.qq"],
            "required": True,
            "string": True,
        },
        "status": {
            "paths": ["data.status"],
            "required": True,
            "string": True,
        },
        "ban_time": {
            "paths": ["data.ban_time", "data.banTime"],
            "string": True,
        },
        "end_time": {
            "paths": ["data.end_time", "data.endTime", "data.left_time"],
            "string": True,
        },
        "ban_reason": {
            "paths": [
                "data.ban_reason",
                "data.reason",
                "data.punish.reason",
                "data.punish_reason",
            ],
            "default": "第三方接口未提供封禁原因",
            "string": True,
        },
        "message": {"paths": ["msg", "message"], "string": True},
    },
    "templates": {
        "hit": (
            "账号封禁查询结果\n\n"
            "QQ号码：{qq}\n"
            "账号状态：{status}\n"
            "封禁原因：{ban_reason|第三方接口未提供封禁原因}\n"
            "封禁时间：{ban_time|未提供}\n"
            "剩余时间：{end_time|未提供}"
        ),
        "clear": "账号封禁查询结果\n\nQQ号码：{qq}\n账号状态：{status}",
        "unknown": "账号封禁查询失败：第三方响应状态无法识别",
    },
}

LOL2099_PROVIDER: dict[str, Any] = {
    "id": "lolban-lol2099",
    "name": "LOL2099 免费备用接口",
    "enabled": False,
    "request": {
        "method": "POST",
        "url": "https://lol2099.top/",
        "headers": {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://lol2099.top/",
            "X-Requested-With": "XMLHttpRequest",
        },
        "form": {
            "action": "query_lol",
            "qq": "$qq",
        },
        "timeout_seconds": 10,
    },
    "parser": copy.deepcopy(_STANDARD_LOLBAN_PARSER),
}

FOURPNG_PROVIDER: dict[str, Any] = {
    "id": "lolban-4png",
    "name": "4PNG 收费备用接口",
    "enabled": False,
    "request": {
        "method": "GET",
        "url": "https://yun.4png.com/api/query.html",
        "query": {
            "qq": "$qq",
            "token": "$secret:LOL_BAN_4PNG_TOKEN",
        },
        "timeout_seconds": 10,
    },
    "parser": {
        "success": {"path": "code", "op": "eq", "value": 200},
        "error_message_paths": ["msg", "message", "error"],
        "outcomes": [
            {
                "name": "hit",
                "when": {"path": "data.return", "op": "eq", "value": "封禁"},
            },
            {
                "name": "clear",
                "when": {"path": "data.return", "op": "eq", "value": "正常"},
            },
        ],
        "default_outcome": "unknown",
        "fields": {
            "status": {
                "paths": ["data.return"],
                "required": True,
                "string": True,
            },
            "ban_time": {"paths": ["data.banmsg"], "string": True},
            "end_time": {"paths": ["data.rammsg"], "string": True},
            "ban_reason": {
                "default": "第三方接口未提供封禁原因",
                "string": True,
            },
            "message": {"paths": ["msg", "message"], "string": True},
        },
        "templates": {
            "hit": (
                "账号封禁查询结果\n\n"
                "QQ号码：{qq}\n"
                "账号状态：{status}\n"
                "封禁原因：{ban_reason|第三方接口未提供封禁原因}\n"
                "封禁时间：{ban_time|未提供}\n"
                "剩余时间：{end_time|未提供}"
            ),
            "clear": "账号封禁查询结果\n\nQQ号码：{qq}\n账号状态：{status}",
            "unknown": "账号封禁查询失败：第三方响应状态无法识别",
        },
    },
}

RECOMMENDED_LOLBAN_PROVIDERS: tuple[Mapping[str, Any], ...] = (
    LOL2099_PROVIDER,
    FOURPNG_PROVIDER,
)


def ensure_lolban_provider_presets() -> dict[str, Any]:
    """Apply known backup presets once without enabling them.

    Existing provider order and configuration are preserved. A migration marker
    prevents a provider deliberately removed later from being re-created on
    every WebUI restart.
    """

    config, target, using_default = _load_effective_config()
    metadata = config.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        config["metadata"] = metadata
    applied = metadata.get("applied_migrations")
    if not isinstance(applied, list):
        applied = []
        metadata["applied_migrations"] = applied
    if _MIGRATION_ID in applied:
        return {
            "ok": True,
            "changed": False,
            "path": str(target),
            "using_default": using_default,
            "added_provider_ids": [],
        }

    features = config.setdefault("features", {})
    lolban = features.setdefault("lolban", {"operation": "query", "providers": []})
    lolban["operation"] = "query"
    providers = lolban.get("providers")
    if not isinstance(providers, list):
        providers = []
        lolban["providers"] = providers

    existing_ids = {
        str(item.get("id") or item.get("name") or "").strip()
        for item in providers
        if isinstance(item, Mapping)
    }
    added: list[str] = []
    for preset in RECOMMENDED_LOLBAN_PROVIDERS:
        provider_id = str(preset.get("id") or "").strip()
        if not provider_id or provider_id in existing_ids:
            continue
        providers.append(copy.deepcopy(dict(preset)))
        existing_ids.add(provider_id)
        added.append(provider_id)

    applied.append(_MIGRATION_ID)
    result = save_parser_center({"config": config})
    return {
        "ok": True,
        "changed": True,
        "path": str(target),
        "using_default": using_default,
        "added_provider_ids": added,
        "backup_path": str(result.get("backup_path") or ""),
        "enabled": False,
    }
