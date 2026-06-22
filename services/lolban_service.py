import asyncio
import json
import os
import re
from typing import Any, Dict, Tuple

import requests

from cache import TTLCache

UPSTREAM_URL = os.getenv("LOL_BAN_UPSTREAM_URL", "https://lol2099.top/").strip()
TIMEOUT = float(os.getenv("LOL_BAN_TIMEOUT", "10"))
NORMAL_CACHE_SECONDS = int(os.getenv("LOL_BAN_NORMAL_CACHE_SECONDS", "60"))
BANNED_CACHE_SECONDS = int(os.getenv("LOL_BAN_BANNED_CACHE_SECONDS", "300"))

_normal_cache = TTLCache(ttl_seconds=NORMAL_CACHE_SECONDS)
_banned_cache = TTLCache(ttl_seconds=BANNED_CACHE_SECONDS)

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://lol2099.top",
    "referer": "https://lol2099.top/",
}

UNSAFE_MESSAGE_WORDS = (
    "官网", "联系qq", "联系QQ", "请访问", "www.", "http://", "https://",
    "客服", "加q", "加Q", "充值", "购买", "广告",
)


def valid_qq(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,11}", str(value or "").strip()))


def message_is_unsafe(message: str) -> bool:
    return any(word in message for word in UNSAFE_MESSAGE_WORDS)


def clean_payload(qq: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    msg = str(payload.get("msg") or "").strip()
    if message_is_unsafe(msg):
        raise RuntimeError("upstream unsafe message blocked")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = str(data.get("status") or "").strip()
    if status not in {"正常", "封禁"}:
        if "正常" in msg:
            status = "正常"
        elif "封禁" in msg:
            status = "封禁"
    if status not in {"正常", "封禁"}:
        raise RuntimeError("upstream status unknown")

    safe_msg = "此账号状态正常" if status == "正常" else "此账号已被封禁"
    return {
        "code": 200,
        "by": str(payload.get("by") or "q.lolmap.cn"),
        "msg": safe_msg,
        "data": {
            "qq": str(data.get("qq") or qq).strip(),
            "ban_time": str(data.get("ban_time") or "").strip(),
            "end_time": str(data.get("end_time") or ("账号状态正常" if status == "正常" else "")).strip(),
            "status": status,
        },
    }


def format_lolban_text(payload: Dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = str(data.get("status") or "未知")
    lines = ["账号封禁查询结果", str(payload.get("msg") or "查询完成"), ""]
    lines.append(f"QQ号码：{data.get('qq') or '-'}")
    lines.append(f"账号状态：{status}")
    if status == "正常":
        lines.append(f"解封时间：{data.get('end_time') or '账号状态正常'}")
    elif status == "封禁":
        if data.get("ban_time"):
            lines.append(f"封禁时间：{data.get('ban_time')}")
        if data.get("end_time"):
            lines.append(f"剩余时间：{data.get('end_time')}")
    return "\n".join(lines).strip()


def query_upstream(qq: str) -> Dict[str, Any]:
    response = requests.post(
        UPSTREAM_URL,
        headers=HEADERS,
        data={"action": "query_lol", "qq": qq},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="replace").strip().lstrip("\ufeff")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("upstream payload is not object")
    return clean_payload(qq, payload)


def select_cache(payload: Dict[str, Any]) -> Tuple[TTLCache, int]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if data.get("status") == "封禁":
        return _banned_cache, BANNED_CACHE_SECONDS
    return _normal_cache, NORMAL_CACHE_SECONDS


async def get_lolban_result(qq: str) -> Tuple[Dict[str, Any], str, int]:
    key = f"lolban:{qq}"
    for cache in (_normal_cache, _banned_cache):
        cached, ttl = cache.get_with_remaining_ttl(key)
        if isinstance(cached, dict):
            result = dict(cached)
            result["source"] = "cache"
            result["cache_expires_in"] = ttl
            return result, "cache", ttl

    result = await asyncio.to_thread(query_upstream, qq)
    cache, ttl = select_cache(result)
    cache.set(key, result)
    result = dict(result)
    result["source"] = "live"
    result["cache_expires_in"] = ttl
    return result, "live", ttl
