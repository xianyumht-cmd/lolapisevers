from __future__ import annotations

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

from cache import TTLCache
from services.api_parser_center import (
    enabled_providers,
    execute_request,
    parse_response,
    prepare_request,
    to_lolban_payload,
)
from services.persistent_snapshot_store import PersistentSnapshotStore


TIMEOUT = 10.0
NORMAL_CACHE_SECONDS = 60
BANNED_CACHE_SECONDS = 300
STALE_CACHE_SECONDS = 86400
MAX_STALE_ENTRIES = 1024
LOL_BAN_SNAPSHOT_SOURCE_ID = "lolban-last-known-v1"
_DEFAULT_SNAPSHOT_STORE = object()

DEFAULT_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120 Safari/537.36",
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


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _configured_timeout_seconds() -> float:
    return _env_float("LOL_BAN_TIMEOUT", TIMEOUT, minimum=1.0, maximum=60.0)


def valid_qq(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,11}", str(value or "").strip()))


def message_is_unsafe(message: str) -> bool:
    return any(word in str(message or "") for word in UNSAFE_MESSAGE_WORDS)


def _first_text(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def clean_payload(qq: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a third-party ban response without exposing its identity.

    The normalized payload intentionally preserves business data such as
    ``ban_reason`` while replacing provider branding with a generic internal
    value. Public formatters never render ``by`` or provider metadata.
    """

    if not isinstance(payload, dict):
        raise RuntimeError("upstream payload is not object")
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

    upstream_qq = str(data.get("qq") or data.get("uin") or "").strip()
    if upstream_qq and upstream_qq != qq:
        raise RuntimeError("upstream qq mismatch")

    ban_reason = _first_text(
        data,
        "ban_reason",
        "banReason",
        "reason",
        "punish_reason",
        "punishReason",
    )
    punish = data.get("punish") if isinstance(data.get("punish"), dict) else {}
    if not ban_reason:
        ban_reason = _first_text(punish, "reason", "description", "message")
    if status == "封禁" and not ban_reason:
        ban_reason = "第三方接口未提供封禁原因"

    safe_msg = "此账号状态正常" if status == "正常" else "此账号已被封禁"
    normalized: Dict[str, Any] = {
        "code": 200,
        "by": "configured-provider",
        "msg": safe_msg,
        "data": {
            "qq": qq,
            "ban_time": _first_text(data, "ban_time", "banTime", "start_time", "startTime"),
            "end_time": _first_text(data, "end_time", "endTime", "left_time", "leftTime")
            or ("账号状态正常" if status == "正常" else ""),
            "ban_reason": ban_reason,
            "status": status,
        },
    }
    public_text = str(payload.get("public_text") or "").strip()
    if public_text:
        if message_is_unsafe(public_text):
            raise RuntimeError("upstream unsafe public text blocked")
        normalized["public_text"] = public_text
    return normalized


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
        data.setdefault("ban_reason", "第三方接口未提供封禁原因")
    elif status == "正常":
        data.setdefault("banmsg", "账号状态正常")
    return result


def format_lolban_text(payload: Dict[str, Any]) -> str:
    configured_text = str(payload.get("public_text") or "").strip()
    if configured_text:
        return configured_text

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = str(data.get("status") or "未知")
    lines = ["账号封禁查询结果", "", f"QQ号码：{data.get('qq') or '-'}", f"账号状态：{status}"]
    if status == "封禁":
        lines.append(
            f"封禁原因：{data.get('ban_reason') or '第三方接口未提供封禁原因'}"
        )
        if data.get("ban_time"):
            lines.append(f"封禁时间：{data.get('ban_time')}")
        if data.get("end_time"):
            lines.append(f"剩余时间：{data.get('end_time')}")
    if payload.get("source") == "stale":
        lines.append("提示：上游暂时不可用，当前显示最近一次成功结果")
    return "\n".join(lines).strip()


def _safe_provider_name(value: Any, fallback: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return name[:64] or fallback


def _valid_http_url(value: str) -> bool:
    try:
        sample = str(value or "")
        sample = sample.replace("{qq}", "10000").replace("$qq", "10000")
        sample = re.sub(r"\$secret:[A-Za-z_][A-Za-z0-9_]*", "secret", sample)
        parsed = urlparse(sample)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _safe_attempts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        attempt = {
            "provider": _safe_provider_name(item.get("provider"), f"provider-{index}"),
            "ok": bool(item.get("ok")),
            "elapsed_ms": max(0, int(item.get("elapsed_ms") or 0)),
        }
        if not attempt["ok"]:
            attempt["error_class"] = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                str(item.get("error_class") or "failed"),
            )[:96]
        safe.append(attempt)
    return safe


def _sanitize_stored_payload(qq: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = clean_payload(qq, payload)
    provider = str(payload.get("provider") or "").strip()
    if provider:
        sanitized["provider"] = _safe_provider_name(provider, "provider")
    attempts = _safe_attempts(payload.get("attempts"))
    if attempts:
        sanitized["attempts"] = attempts
    return sanitized


@dataclass(frozen=True)
class LolBanProvider:
    name: str
    url: str
    method: str = "GET"
    qq_param: str = "qq"
    timeout_seconds: float = TIMEOUT
    headers: Mapping[str, Any] = field(default_factory=dict)
    form: Mapping[str, Any] = field(default_factory=dict)
    query_params: Mapping[str, Any] = field(default_factory=dict)
    json_body: Any = None
    parser: Mapping[str, Any] = field(default_factory=dict)

    def query(self, qq: str) -> Dict[str, Any]:
        url = self.url.replace("{qq}", "$qq")
        query = dict(self.query_params)
        form = dict(self.form)
        if "$qq" not in url:
            if self.method.upper() == "GET" and self.qq_param not in query:
                query[self.qq_param] = "$qq"
            elif self.method.upper() != "GET" and self.qq_param not in form:
                form[self.qq_param] = "$qq"
        profile = {
            "id": self.name,
            "request": {
                "method": self.method,
                "url": url,
                "headers": {**DEFAULT_HEADERS, **dict(self.headers)},
                "query": query,
                "form": form,
                "json": self.json_body,
                "timeout_seconds": self.timeout_seconds,
            },
            "parser": dict(self.parser),
        }
        prepared = prepare_request(profile, {"qq": qq})
        execution = execute_request(prepared)
        if self.parser:
            parsed = parse_response(profile, execution.payload, status_code=execution.status_code)
            return to_lolban_payload(qq, parsed)
        if not 200 <= execution.status_code < 300:
            raise RuntimeError(f"upstream http status {execution.status_code}")
        if not isinstance(execution.payload, dict):
            raise RuntimeError("upstream payload is not object")
        return clean_payload(qq, execution.payload)


def _provider_from_raw(raw: Mapping[str, Any], index: int) -> Optional[LolBanProvider]:
    if raw.get("enabled") is False:
        return None
    request_spec = raw.get("request") if isinstance(raw.get("request"), Mapping) else raw
    url = str(request_spec.get("url") or raw.get("url") or "").strip()
    if not _valid_http_url(url):
        return None
    method = str(request_spec.get("method") or raw.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST"}:
        return None
    headers = request_spec.get("headers") if isinstance(request_spec.get("headers"), Mapping) else {}
    form = request_spec.get("form") if isinstance(request_spec.get("form"), Mapping) else {}
    query = request_spec.get("query") if isinstance(request_spec.get("query"), Mapping) else {}
    parser = raw.get("parser") if isinstance(raw.get("parser"), Mapping) else {}
    json_body = request_spec.get("json") if "json" in request_spec else request_spec.get("json_body")
    default_timeout = _configured_timeout_seconds()
    try:
        timeout_seconds = max(
            1.0,
            min(
                float(
                    request_spec.get("timeout_seconds")
                    or raw.get("timeout_seconds")
                    or default_timeout
                ),
                60.0,
            ),
        )
    except (TypeError, ValueError):
        timeout_seconds = default_timeout
    return LolBanProvider(
        name=_safe_provider_name(raw.get("id") or raw.get("name"), f"provider-{index}"),
        url=url,
        method=method,
        qq_param=str(raw.get("qq_param") or "qq").strip() or "qq",
        timeout_seconds=timeout_seconds,
        headers={str(k): v for k, v in headers.items()},
        form={str(k): v for k, v in form.items()},
        query_params={str(k): v for k, v in query.items()},
        json_body=json_body,
        parser={str(k): v for k, v in parser.items()},
    )


def load_providers() -> List[LolBanProvider]:
    providers: List[LolBanProvider] = []

    for index, raw in enumerate(enabled_providers("lolban"), start=1):
        provider = _provider_from_raw(raw, index)
        if provider is not None:
            providers.append(provider)

    raw_json = str(os.getenv("LOL_BAN_PROVIDERS_JSON") or "").strip()
    if raw_json:
        try:
            source = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LOL_BAN_PROVIDERS_JSON is invalid JSON") from exc
        if not isinstance(source, list):
            raise RuntimeError("LOL_BAN_PROVIDERS_JSON must be a JSON array")
        offset = len(providers)
        for index, raw in enumerate(source, start=1):
            if isinstance(raw, dict):
                provider = _provider_from_raw(raw, offset + index)
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
                timeout_seconds=_configured_timeout_seconds(),
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
        max_stale_entries: int = MAX_STALE_ENTRIES,
        snapshot_store: Any = _DEFAULT_SNAPSHOT_STORE,
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
        self._restored_from_snapshot: set[str] = set()
        self._last_success_at = ""
        self._last_error_at = ""
        self._last_error_class = ""
        self._configuration_error_code = ""
        self._configuration_error_class = ""
        self._snapshot_status = "disabled"
        self._snapshot_write_error_class = ""

        if snapshot_store is _DEFAULT_SNAPSHOT_STORE:
            enabled = _env_bool("LOL_BAN_SNAPSHOT_ENABLED", True)
            self.snapshot_store = (
                PersistentSnapshotStore()
                if enabled and self.stale_cache_seconds > 0
                else None
            )
        else:
            self.snapshot_store = snapshot_store
        self._restore_persistent_last_known()

    def _lock_for(self, qq: str) -> threading.Lock:
        return self._query_locks[hash(qq) % len(self._query_locks)]

    def _purge_stale_locked(self, now: float) -> None:
        if self.stale_cache_seconds <= 0:
            self._last_known.clear()
            self._restored_from_snapshot.clear()
            return
        expired = [
            qq
            for qq, (_payload, captured_at) in self._last_known.items()
            if now - captured_at > self.stale_cache_seconds
        ]
        for qq in expired:
            self._last_known.pop(qq, None)
            self._restored_from_snapshot.discard(qq)

    def _snapshot_payload_locked(self) -> Dict[str, Any]:
        return {
            "entries": [
                {
                    "qq": qq,
                    "captured_at_epoch": captured_at,
                    "payload": copy.deepcopy(payload),
                }
                for qq, (payload, captured_at) in self._last_known.items()
            ],
            "max_entries": self.max_stale_entries,
        }

    def _persist_last_known_locked(self) -> None:
        if self.snapshot_store is None or self.stale_cache_seconds <= 0:
            self._snapshot_status = "disabled"
            return
        try:
            result = self.snapshot_store.save(
                LOL_BAN_SNAPSHOT_SOURCE_ID,
                self._snapshot_payload_locked(),
                {
                    "entry_count": len(self._last_known),
                    "stale_cache_seconds": self.stale_cache_seconds,
                },
            )
            self._snapshot_status = str(result.get("status") or "saved")
            self._snapshot_write_error_class = ""
        except Exception as exc:
            self._snapshot_status = "write_error"
            self._snapshot_write_error_class = type(exc).__name__

    def _restore_persistent_last_known(self) -> None:
        if self.snapshot_store is None or self.stale_cache_seconds <= 0:
            self._snapshot_status = "disabled"
            return
        try:
            loaded = self.snapshot_store.load(
                LOL_BAN_SNAPSHOT_SOURCE_ID,
                max_age_seconds=self.stale_cache_seconds,
            )
        except Exception as exc:
            self._snapshot_status = "load_error"
            self._snapshot_write_error_class = type(exc).__name__
            return
        self._snapshot_status = loaded.status
        if not loaded.ok or not isinstance(loaded.payload, dict):
            return
        entries = loaded.payload.get("entries")
        if not isinstance(entries, list):
            self._snapshot_status = "invalid_payload"
            return

        now = time.time()
        restored: OrderedDict[str, Tuple[Dict[str, Any], float]] = OrderedDict()
        for item in entries:
            if not isinstance(item, dict):
                continue
            qq = str(item.get("qq") or "").strip()
            raw_payload = item.get("payload")
            try:
                captured_at = float(item.get("captured_at_epoch"))
            except (TypeError, ValueError):
                continue
            if not valid_qq(qq) or not isinstance(raw_payload, dict):
                continue
            if captured_at <= 0 or now - captured_at > self.stale_cache_seconds:
                continue
            try:
                stored = _sanitize_stored_payload(qq, raw_payload)
            except Exception:
                continue
            restored.pop(qq, None)
            restored[qq] = (stored, captured_at)
            while len(restored) > self.max_stale_entries:
                restored.popitem(last=False)

        with self._last_known_lock:
            self._last_known = restored
            self._restored_from_snapshot = set(restored.keys())
        self._snapshot_status = "restored" if restored else "empty"

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
                result["stale_origin"] = ""
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
        banned = data.get("status") == "封禁"
        ttl = self.banned_cache_seconds if banned else self.normal_cache_seconds
        cache = self._banned_cache if banned else self._normal_cache
        stored = _sanitize_stored_payload(qq, payload)
        stored["provider"] = _safe_provider_name(provider, "provider")
        stored["attempts"] = _safe_attempts(attempts)
        cache.set(f"lolban:{qq}", copy.deepcopy(stored))
        with self._last_known_lock:
            now = time.time()
            self._purge_stale_locked(now)
            self._last_known.pop(qq, None)
            self._last_known[qq] = (copy.deepcopy(stored), now)
            self._restored_from_snapshot.discard(qq)
            while len(self._last_known) > self.max_stale_entries:
                removed_qq, _ = self._last_known.popitem(last=False)
                self._restored_from_snapshot.discard(removed_qq)
            self._persist_last_known_locked()
        self._last_success_at = datetime.now(timezone.utc).isoformat()

        result = copy.deepcopy(stored)
        result["source"] = "live"
        result["cache_expires_in"] = ttl
        result["stale_age_seconds"] = 0
        result["stale_origin"] = ""
        result["fallback_reason"] = "provider_fallback" if len(attempts) > 1 else ""
        if self._snapshot_write_error_class:
            result["snapshot_write_error"] = self._snapshot_write_error_class
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
            restored = qq in self._restored_from_snapshot
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
        result["stale_origin"] = "persistent_snapshot" if restored else "memory"
        result["fallback_reason"] = "all_providers_failed"
        result["attempts"] = _safe_attempts(attempts)
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
                    return self._cache_live_result(
                        qq,
                        payload,
                        provider.name,
                        attempts,
                    )
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
            self._last_error_class = (
                attempts[-1].get("error_class", "providers_unavailable")
                if attempts
                else "providers_not_configured"
            )
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
            restored_entries = len(self._restored_from_snapshot)
        return {
            "configured": bool(self.providers),
            "provider_count": len(self.providers),
            "providers": [provider.name for provider in self.providers],
            "fresh_cache_entries": len(self._normal_cache) + len(self._banned_cache),
            "stale_cache_entries": stale_entries,
            "persistent_snapshot_enabled": self.snapshot_store is not None,
            "persistent_snapshot_status": self._snapshot_status,
            "persistent_snapshot_restored_entries": restored_entries,
            "persistent_snapshot_write_error_class": self._snapshot_write_error_class,
            "last_success_at": self._last_success_at,
            "last_error_at": self._last_error_at,
            "last_error_class": self._last_error_class,
            "configuration_error_code": self._configuration_error_code,
            "configuration_error_class": self._configuration_error_class,
        }


def _service_settings_from_environment() -> dict[str, int]:
    return {
        "normal_cache_seconds": _env_int(
            "LOL_BAN_NORMAL_CACHE_SECONDS",
            NORMAL_CACHE_SECONDS,
            minimum=1,
        ),
        "banned_cache_seconds": _env_int(
            "LOL_BAN_BANNED_CACHE_SECONDS",
            BANNED_CACHE_SECONDS,
            minimum=1,
        ),
        "stale_cache_seconds": _env_int(
            "LOL_BAN_STALE_CACHE_SECONDS",
            STALE_CACHE_SECONDS,
            minimum=0,
        ),
        "max_stale_entries": _env_int(
            "LOL_BAN_MAX_STALE_ENTRIES",
            MAX_STALE_ENTRIES,
            minimum=1,
        ),
    }


def create_lolban_service(*, strict_configuration: bool = False) -> LolBanService:
    """Build a service from the current process environment.

    Initial startup is tolerant so an optional provider configuration error does
    not break the whole API process. Runtime reloads use strict mode so a bad
    candidate cannot replace the last known working service.
    """

    settings = _service_settings_from_environment()
    try:
        return LolBanService(**settings)
    except Exception as exc:
        if strict_configuration:
            raise
        service = LolBanService([], **settings)
        service._configuration_error_code = "invalid_provider_configuration"
        service._configuration_error_class = type(exc).__name__
        return service
