from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from lanzou_update_push_api_server.providers import FileEntry, utc_now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "target-file-watch.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "target-file-watch-state.json"
STATE_VERSION = 1
SCHEMA = "target-file-push.v1"


class TargetFileWatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetFileWatchConfig:
    enabled: bool = False
    source_url: str = ""
    callback_url: str = ""
    callback_token: str = ""
    check_interval_seconds: int = 300


@dataclass(frozen=True)
class ResolvedTargetFile:
    fingerprint: str
    stable_id: str
    name: str
    size: str
    modified_time: str
    share_link: str
    provider: str
    direct_url: str = ""

    def public_file(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "modified_at": self.modified_time,
            "stable_id": self.stable_id,
        }


def _config_path() -> Path:
    raw = str(os.getenv("TARGET_FILE_WATCH_CONFIG_PATH") or "").strip()
    return Path(raw).expanduser().resolve() if raw else DEFAULT_CONFIG_PATH


def _state_path() -> Path:
    raw = str(os.getenv("TARGET_FILE_WATCH_STATE_PATH") or "").strip()
    return Path(raw).expanduser().resolve() if raw else DEFAULT_STATE_PATH


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return parts.scheme in {"http", "https"} and bool(parts.netloc)
    except Exception:
        return False


def _is_lanzou_url(value: str) -> bool:
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except Exception:
        return False
    return bool(host) and (
        "lanzou" in host
        or host.endswith("lanzn.com")
        or host.endswith("lanwp.com")
    )


def _stable_url(value: str) -> str:
    text = str(value or "").strip()
    try:
        parts = urlsplit(text)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except Exception:
        return text.split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _atomic_json_write(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            os.chmod(temp, mode)
        except OSError:
            pass
        temp.replace(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def normalize_config(value: Any) -> TargetFileWatchConfig:
    raw = value if isinstance(value, dict) else {}
    enabled = raw.get("enabled") is True
    source_url = str(raw.get("source_url") or raw.get("sourceUrl") or "").strip()
    callback_url = str(raw.get("callback_url") or raw.get("callbackUrl") or "").strip()
    callback_token = str(raw.get("callback_token") or raw.get("callbackToken") or "").strip()
    try:
        interval = int(raw.get("check_interval_seconds") or raw.get("checkIntervalSeconds") or 300)
    except (TypeError, ValueError):
        interval = 300
    interval = max(30, min(interval, 86_400))

    if source_url and not _is_lanzou_url(source_url):
        raise TargetFileWatchError("source_url 必须是有效的蓝奏网盘链接")
    if callback_url and not _is_http_url(callback_url):
        raise TargetFileWatchError("callback_url 必须是有效的 http/https 地址")
    if enabled:
        if not source_url:
            raise TargetFileWatchError("启用定向文件监控前必须配置 source_url")
        if not callback_url:
            raise TargetFileWatchError("启用定向文件监控前必须配置 callback_url")
        if len(callback_token) < 16:
            raise TargetFileWatchError("启用定向文件监控前必须配置至少 16 位 callback_token")

    return TargetFileWatchConfig(
        enabled=enabled,
        source_url=source_url,
        callback_url=callback_url,
        callback_token=callback_token,
        check_interval_seconds=interval,
    )


def _file_fingerprint(file: FileEntry) -> str:
    payload = file.canonical_fingerprint_payload()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _event_id(source_url: str, fingerprint: str) -> str:
    encoded = f"{_stable_url(source_url)}\n{fingerprint}".encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _choose_target_file(source_url: str, files: list[FileEntry]) -> FileEntry:
    if not files:
        raise TargetFileWatchError("蓝奏链接未解析到文件")
    if len(files) == 1:
        return files[0]

    source = _stable_url(source_url)
    exact = [item for item in files if _stable_url(item.link) == source]
    if len(exact) == 1:
        return exact[0]

    raise TargetFileWatchError(
        f"指定链接解析到 {len(files)} 个文件；定向推送不会猜测目标文件，请使用单文件蓝奏分享链接"
    )


def _direct_candidates(file: FileEntry) -> list[str]:
    raw = file.raw if isinstance(file.raw, dict) else {}
    values = [
        raw.get("downurl"),
        raw.get("download"),
        raw.get("file_url"),
        raw.get("download_url"),
        raw.get("url"),
        raw.get("link"),
        file.link,
    ]
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if _is_http_url(text) and text not in output:
            output.append(text)
    return output


class TargetFileWatchService:
    """Shared state, lifecycle and callback transport for target-file-watch.

    Production directory resolution is supplied by SafeTargetFileWatchService;
    this base class intentionally does not instantiate the legacy Lanzou provider
    chain at import time.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("LOLDataSystem.TargetFileWatch")
        self.resolver: Any = None
        self._config = TargetFileWatchConfig()
        self._state: dict[str, Any] = self._empty_state()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._check_lock = asyncio.Lock()
        self._load_config()
        self._load_state()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "source_url": "",
            "baseline": None,
            "pending": None,
            "last_check_at": "",
            "last_success_at": "",
            "last_delivery_at": "",
            "last_error_at": "",
            "last_error_code": "",
            "last_event_id": "",
        }

    def _load_config(self) -> None:
        path = _config_path()
        if not path.exists():
            _atomic_json_write(path, asdict(TargetFileWatchConfig()))
            self._config = TargetFileWatchConfig()
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            self._config = normalize_config(raw)
        except Exception as exc:
            self.logger.error("target file config load failed: %s", type(exc).__name__)
            self._config = TargetFileWatchConfig()

    def _load_state(self) -> None:
        path = _state_path()
        if not path.exists():
            self._state = self._empty_state()
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict) or int(raw.get("version") or 0) != STATE_VERSION:
                raise ValueError("invalid state")
            self._state = {**self._empty_state(), **raw}
        except Exception as exc:
            self.logger.error("target file state load failed: %s", type(exc).__name__)
            self._state = self._empty_state()

    def _save_state(self) -> None:
        _atomic_json_write(_state_path(), self._state)

    def get_config(self) -> TargetFileWatchConfig:
        return self._config

    def sanitized_config(self) -> dict[str, Any]:
        return {
            "enabled": self._config.enabled,
            "source_url": self._config.source_url,
            "callback_url": self._config.callback_url,
            "callback_token_configured": bool(self._config.callback_token),
            "check_interval_seconds": self._config.check_interval_seconds,
        }

    def status(self) -> dict[str, Any]:
        pending = self._state.get("pending") if isinstance(self._state.get("pending"), dict) else None
        baseline = self._state.get("baseline") if isinstance(self._state.get("baseline"), dict) else None
        return {
            "ok": True,
            "running": self._task is not None and not self._task.done(),
            "config": self.sanitized_config(),
            "baseline": baseline,
            "pending": pending,
            "last_check_at": self._state.get("last_check_at") or "",
            "last_success_at": self._state.get("last_success_at") or "",
            "last_delivery_at": self._state.get("last_delivery_at") or "",
            "last_error_at": self._state.get("last_error_at") or "",
            "last_error_code": self._state.get("last_error_code") or "",
            "last_event_id": self._state.get("last_event_id") or "",
        }

    def save_config(self, value: Any) -> dict[str, Any]:
        next_config = normalize_config(value)
        previous_source = _stable_url(self._config.source_url)
        next_source = _stable_url(next_config.source_url)
        _atomic_json_write(_config_path(), asdict(next_config))
        self._config = next_config
        if previous_source != next_source:
            self._state = self._empty_state()
            self._state["source_url"] = next_config.source_url
            self._save_state()
        return self.status()

    def rebaseline(self) -> dict[str, Any]:
        self._state = self._empty_state()
        self._state["source_url"] = self._config.source_url
        self._save_state()
        return self.status()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="target-file-watch")
        self.logger.info("target file watch service started")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        self.logger.info("target file watch service stopped")

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            self._load_config()
            if self._config.enabled:
                try:
                    await self.check_once()
                except Exception:
                    self.logger.exception("scheduled target file check failed")
            interval = max(30, self._config.check_interval_seconds)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _file_state(resolved: ResolvedTargetFile) -> dict[str, Any]:
        return {
            "fingerprint": resolved.fingerprint,
            "stable_id": resolved.stable_id,
            "name": resolved.name,
            "size": resolved.size,
            "modified_time": resolved.modified_time,
            "share_link": resolved.share_link,
            "provider": resolved.provider,
        }

    async def check_once(self) -> dict[str, Any]:
        async with self._check_lock:
            self._load_config()
            if not self._config.enabled:
                return {"ok": False, "skipped": True, "error": "target_file_watch_disabled"}
            if self.resolver is None:
                raise TargetFileWatchError("target_file_resolver_unavailable")

            now = utc_now_iso()
            try:
                current = await asyncio.to_thread(self.resolver.resolve_metadata, self._config.source_url)
                self._state["last_check_at"] = now
                self._state["last_success_at"] = now
                self._state["last_error_code"] = ""
                self._state["source_url"] = self._config.source_url

                baseline = self._state.get("baseline") if isinstance(self._state.get("baseline"), dict) else None
                current_state = self._file_state(current)
                if baseline is None:
                    self._state["baseline"] = current_state
                    self._state["pending"] = None
                    self._save_state()
                    return {
                        "ok": True,
                        "state": "baselined",
                        "uploaded": False,
                        "file": current.public_file(),
                        "fingerprint": current.fingerprint,
                    }

                baseline_fp = str(baseline.get("fingerprint") or "")
                if current.fingerprint == baseline_fp:
                    self._state["pending"] = None
                    self._save_state()
                    return {
                        "ok": True,
                        "state": "unchanged",
                        "uploaded": False,
                        "fingerprint": current.fingerprint,
                    }

                event_id = _event_id(self._config.source_url, current.fingerprint)
                pending = {
                    **current_state,
                    "event_id": event_id,
                    "detected_at": now,
                }
                self._state["pending"] = pending
                self._save_state()

                delivery = await asyncio.to_thread(
                    self.resolver.resolve_for_delivery,
                    self._config.source_url,
                    current.fingerprint,
                )
                payload = {
                    "schema": SCHEMA,
                    "event_id": event_id,
                    "source_url": self._config.source_url,
                    "fingerprint": current.fingerprint,
                    "detected_at": now,
                    "file": delivery.public_file(),
                    "direct_url": delivery.direct_url,
                }
                response = await asyncio.to_thread(self._deliver, payload)

                self._state["baseline"] = current_state
                self._state["pending"] = None
                self._state["last_delivery_at"] = utc_now_iso()
                self._state["last_event_id"] = event_id
                self._state["last_error_code"] = ""
                self._save_state()
                return {
                    "ok": True,
                    "state": "delivered",
                    "uploaded": True,
                    "event_id": event_id,
                    "file": current.public_file(),
                    "callback": response,
                }
            except Exception as exc:
                self._state["last_check_at"] = now
                self._state["last_error_at"] = utc_now_iso()
                self._state["last_error_code"] = str(exc)[:240]
                self._save_state()
                raise

    def _deliver(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self._config.callback_url,
            json=payload,
            timeout=30,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "x-target-file-token": self._config.callback_token,
            },
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code < 200 or response.status_code >= 300:
            raise TargetFileWatchError(f"GroupGuard 回调失败 HTTP {response.status_code}")
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TargetFileWatchError("GroupGuard 未确认群文件上传成功")
        return {
            "ok": True,
            "uploaded": body.get("uploaded") is True,
            "deduplicated": body.get("deduplicated") is True,
            "cleanup_pending": body.get("cleanupPending") is True,
        }
