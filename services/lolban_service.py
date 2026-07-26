import asyncio
import copy
import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import requests

from cache import TTLCache


TIMEOUT = float(os.getenv("LOL_BAN_TIMEOUT", "10"))
NORMAL_CACHE_SECONDS = int(os.getenv("LOL_BAN_NORMAL_CACHE_SECONDS", "60"))
BANNED_CACHE_SECONDS = int(os.getenv("LOL_BAN_BANNED_CACHE_SECONDS", "300"))
STALE_CACHE_SECONDS = int(os.getenv("LOL_BAN_STALE_CACHE_SECONDS", "86400"))

DEFAULT_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
}

UNSAFE_MESSAGE_WORDS = (
    "官网",
    "联系qq",
    "联系QQ",
    "请访问",
    "www.",
    "http://",
    "https://",
    "客服",
    "加q",
    "加Q",
    "充值",
    "购买",
    "广告",
)


def valid_qq(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,11}", str(value or "").strip()))


def message_is_unsafe(message: str) -> bool:
    return any(word in message for word in UNSAFE_MESSAGE_WORDS)


def clean_payload(qq: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    msg = str(payload.get("msg") or payload.get("message") or "").strip()
    if message_is_unsafe(msg):
        raise RuntimeError("upstream unsafe message blocked")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(data.get("status") or data.get("return") or "").strip()
    if status not in {"正常", "封禁"}:
        if "正常" in msg or "未封" in msg:
            status = "正常"
        elif "封禁" in msg or "被封" in msg:
            status = "封禁"
    if status not in {"正常", "封禁"}:
        raise RuntimeError("upstream status unknown")
    upstream_qq = str(data.get("qq") or "").strip()
    if upstream_qq and upstream_qq != qq:
        raise RuntimeError("upstream qq mismatch")

    safe_msg = "此账号状态正常" if status == "正常" else "此账号已被封禁"
    return {
        "code": 200,
        "by": str(payload.get("by") or "configured-provider"),
        "msg": safe_msg,
        "data": {
            "qq": qq,
            "ban_time": str(data.get("ban_time") or data.get("banTime") or "").strip(),
            "end_time": str(
                data.get("end_time")
                or data.get("endTime")
                or data.get("left_time")
                or ("账号状态正常" if status == "正常" else "")
            ).strip(),
            "status": status,
        },
    }


def apply_compat_payload(payload: Dict[str, Any], compat: str = "") -> Dict[str, Any]:
    """Return a JSON-compatible copy with optional legacy/NapCat fields."""

    mode = str(compat or "").strip().lower()
    result = dict(payload)
    source_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data = dict(source_data)
    result["data"] = data
    if mode not in {"napcat", "legacy", "plugin", "bot", "1", "true"}:
        return result

    status = str(data.get("status") or "").strip()
    if status == "封禁":
        end_time = str(data.get("end_time") or "").strip()
        if end_time:
            data.setdefault("left_time", f"剩余时间：{end_time}")
        data.setdefault("banmsg", "账号封禁中")
    elif status == "正常":
        data.setdefault("banmsg", "账号状态正常")
    return result


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
    if payload.get("source") == "stale":
        lines.append("数据来源：最近一次成功结果（上游暂时不可用）")
    return "\n".join(lines).strip()


def _safe_provider_name(value: Any, fallback: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return name[:64] or fallback


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.replace("{qq}", "10000"))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


@dataclass(frozen=True)
class LolBanProvider:
    name: str
    url: str
    method: str = "GET"
    qq_param: str = "qq"
    timeout_seconds: float = TIMEOUT
    headers: Mapping[str, str] = field(default_factory=dict)
    form: Mapping[str, str] = field(default_factory=dict)

    def query(self, qq: str) -> Dict[str, Any]:
        method = self.method.upper()
        headers = {**DEFAULT_HEADERS, **{str(k): str(v) for k, v in self.headers.items()}}
        url = self.url.replace("{qq}", qq)
        kwargs: Dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout_seconds,
        }
        if "{qq}" not in self.url:
            if method == "GET":
                kwargs["params"] = {self.qq_param: qq}
            else:
                kwargs["data"] = {**dict(self.form), self.qq_param: qq}
        elif method != "GET":
            kwargs["data"] = dict(self.form)
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        text = response.content.decode("utf-8", errors="replace").strip().lstrip("\ufeff")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise RuntimeError("upstream payload is not object")
        return clean_payload(qq, payload)


def _provider_from_raw(raw: Mapping[str, Any], index: int) -> Optional[LolBanProvider]:
    url = str(raw.get("url") or "").strip()
    if not _valid_http_url(url):
        return None
    method = str(raw.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST"}:
        return None
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    form = raw.get("form") if isinstance(raw.get("form"), dict) else {}
    try:
        timeout_seconds = max(1.0, min(float(raw.get("timeout_seconds") or TIMEOUT), 60.0))
    except (TypeError, ValueError):
        timeout_seconds = TIMEOUT
    return LolBanProvider(
        name=_safe_provider_name(raw.get("name"), f"provider-{index}"),
        url=url,
        method=method,
        qq_param=str(raw.get("qq_param") or "qq").strip() or "qq",
        timeout_seconds=timeout_seconds,
        headers={str(k): str(v) for k, v in headers.items()},
        form={str(k): str(v) for k, v in form.items()},
    )


def load_providers() -> List[LolBanProvider]:
    providers: List[LolBanProvider] = []
    raw_json = str(os.getenv("LOL_BAN_PROVIDERS_JSON") or "").strip()
    if raw_json:
        try:
            source = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LOL_BAN_PROVIDERS_JSON is invalid JSON") from exc
        if not isinstance(source, list):
            raise RuntimeError("LOL_BAN_PROVIDERS_JSON must be a JSON array")
        for index, raw in enumerate(source, start=1):
            if isinstance(raw, dict):
                provider = _provider_from_raw(raw, index)
                if provider is not None:
                    providers.append(provider)

    legacy_url = str(os.getenv("LOL_BAN_UPSTREAM_URL") or "").strip()
    if legacy_url and _valid_http_url(legacy_url):
        providers.append(
            LolBanProvider(
                name="legacy-form",
                url=legacy_url,
                method="POST",
                qq_param="qq",
                form={"action": "query_lol"},
                headers={
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "x-requested-with": "XMLHttpRequest",
                },
            )
        )

    deduplicated: List[LolBanProvider] = []
    seen: set[Tuple[str, str, str]] = set()
    for provider in providers:
        key = (provider.name, provider.method, provider.url)
        if key not in seen:
            seen.add(key)
            deduplicated.append(provider)
    return deduplicated


class LolBanService:
    def __init__(
        self,
        providers: Optional[Iterable[LolBanProvider]] = None,
        *,
        normal_cache_seconds: int = NORMAL_CACHE_SECONDS,
        banned_cache_seconds: int = BANNED_CACHE_SECONDS,
        stale_cache_seconds: int = STALE_CACHE_SECONDS,
        max_stale_entries: int = 1024,
    ) -> None:
        self.providers = list(providers if providers is not None else load_providers())
        self.normal_cache_seconds = max(1, int(normal_cache_seconds))
        self.banned_cache_seconds = max(1, int(banned_cache_seconds))
        self.stale_cache_seconds = max(0, int(stale_cache_seconds))
        self.max_stale_entries = max(1, int(max_stale_entries))
        self._normal_cache = TTLCache(ttl_seconds=self.normal_cache_seconds)
        self._banned_cache = TTLCache(ttl_seconds=self.banned_cache_seconds)
        self._last_known: OrderedDict[str, Tuple[Dict[str, Any], float]] = OrderedDict()
        self._last_known_lock = threading.Lock()
        self._query_locks = [threading.Lock() for _ in range(64)]
        self._last_success_at = ""
        self._last_error_at = ""
        self._last_error_class = ""
        self._configuration_error_code = ""
        self._configuration_error_class = ""

    def _lock_for(self, qq: str) -> threading.Lock:
        return self._query_locks[hash(qq) % len(self._query_locks)]

    def _purge_stale_locked(self, now: float) -> None:
        if self.stale_cache_seconds <= 0:
            self._last_known.clear()
            return
        expired = [
            qq
            for qq, (_payload, captured_at) in self._last_known.items()
            if now - captured_at > self.stale_cache_seconds
        ]
        for qq in expired:
            self._last_known.pop(qq, None)

    def _fresh_result(self, qq: str) -> Optional[Tuple[Dict[str, Any], str, int]]:
        key = f"lolban:{qq}"
        for cache in (self._normal_cache, self._banned_cache):
            cached, ttl = cache.get_with_remaining_ttl(key)
            if isinstance(cached, dict):
                result = copy.deepcopy(cached)
                result["source"] = "cache"
                result["cache_expires_in"] = ttl
                result["stale_age_seconds"] = 0
                result["fallback_reason"] = ""
                return result, "cache", ttl
        return None

    def _cache_live_result(
        self,
        qq: str,
        payload: Dict[str, Any],
        provider: str,
        attempts: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], str, int]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        ttl = self.banned_cache_seconds if data.get("status") == "封禁" else self.normal_cache_seconds
        cache = self._banned_cache if data.get("status") == "封禁" else self._normal_cache
        stored = copy.deepcopy(payload)
        stored["provider"] = provider
        stored["attempts"] = list(attempts)
        cache.set(f"lolban:{qq}", stored)
        with self._last_known_lock:
            now = time.time()
            self._purge_stale_locked(now)
            self._last_known.pop(qq, None)
            self._last_known[qq] = (copy.deepcopy(stored), now)
            while len(self._last_known) > self.max_stale_entries:
                self._last_known.popitem(last=False)
        self._last_success_at = datetime.now(timezone.utc).isoformat()

        result = copy.deepcopy(stored)
        result["source"] = "live"
        result["cache_expires_in"] = ttl
        result["stale_age_seconds"] = 0
        result["fallback_reason"] = "provider_fallback" if len(attempts) > 1 else ""
        return result, "live", ttl

    def _stale_result(
        self,
        qq: str,
        attempts: List[Dict[str, Any]],
    ) -> Optional[Tuple[Dict[str, Any], str, int]]:
        if self.stale_cache_seconds <= 0:
            return None
        with self._last_known_lock:
            self._purge_stale_locked(time.time())
            item = self._last_known.get(qq)
        if item is None:
            return None
        stored, captured_at = item
        age = max(0, int(time.time() - captured_at))
        if age > self.stale_cache_seconds:
            return None
        result = copy.deepcopy(stored)
        result["source"] = "stale"
        result["cache_expires_in"] = 0
        result["stale_age_seconds"] = age
        result["fallback_reason"] = "all_providers_failed"
        result["attempts"] = list(attempts)
        return result, "stale", 0

    def _query_sync(self, qq: str) -> Tuple[Dict[str, Any], str, int]:
        with self._lock_for(qq):
            cached = self._fresh_result(qq)
            if cached is not None:
                return cached

            attempts: List[Dict[str, Any]] = []
            for provider in self.providers:
                started = time.monotonic()
                try:
                    payload = provider.query(qq)
                    attempts.append(
                        {
                            "provider": provider.name,
                            "ok": True,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                        }
                    )
                    return self._cache_live_result(qq, payload, provider.name, attempts)
                except Exception as exc:
                    attempts.append(
                        {
                            "provider": provider.name,
                            "ok": False,
                            "error_class": type(exc).__name__,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                        }
                    )

            self._last_error_at = datetime.now(timezone.utc).isoformat()
            self._last_error_class = attempts[-1].get("error_class", "providers_unavailable") if attempts else "providers_not_configured"
            stale = self._stale_result(qq, attempts)
            if stale is not None:
                return stale
            summary = ",".join(
                f"{attempt['provider']}:{attempt.get('error_class', 'failed')}"
                for attempt in attempts
            ) or "providers_not_configured"
            raise RuntimeError(f"lolban providers unavailable ({summary})")

    async def get_result(self, qq: str) -> Tuple[Dict[str, Any], str, int]:
        cached = self._fresh_result(qq)
        if cached is not None:
            return cached
        return await asyncio.to_thread(self._query_sync, qq)

    def health(self) -> Dict[str, Any]:
        with self._last_known_lock:
            self._purge_stale_locked(time.time())
            stale_entries = len(self._last_known)
        return {
            "configured": bool(self.providers),
            "provider_count": len(self.providers),
            "providers": [provider.name for provider in self.providers],
            "fresh_cache_entries": len(self._normal_cache) + len(self._banned_cache),
            "stale_cache_entries": stale_entries,
            "last_success_at": self._last_success_at,
            "last_error_at": self._last_error_at,
            "last_error_class": self._last_error_class,
            "configuration_error_code": self._configuration_error_code,
            "configuration_error_class": self._configuration_error_class,
        }


def _create_default_service() -> LolBanService:
    try:
        return LolBanService()
    except Exception as exc:
        service = LolBanService([])
        service._configuration_error_code = "invalid_provider_configuration"
        service._configuration_error_class = type(exc).__name__
        return service


_default_service = _create_default_service()


async def get_lolban_result(qq: str) -> Tuple[Dict[str, Any], str, int]:
    return await _default_service.get_result(qq)


def get_lolban_health() -> Dict[str, Any]:
    return _default_service.health()
