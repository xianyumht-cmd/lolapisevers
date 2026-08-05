from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "config.json"
DEFAULT_STATE_PATH = PACKAGE_DIR / "state.json"


@dataclass(frozen=True)
class WatcherConfig:
    id: str
    title: str
    url: str
    password: str = ""
    enabled: bool = True
    max_pages: int = 20


@dataclass(frozen=True)
class NotifyTargetConfig:
    name: str
    url: str
    enabled: bool = True
    timeout_seconds: float = 8.0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 6178
    scan_interval_seconds: int = 300
    scan_batch_size: int = 0
    scan_batch_pause_seconds: int = 0
    scan_on_start: bool = True
    provider_order: list[str] = field(default_factory=lambda: ["lanzou_web", "wer_api"])
    wer_api_endpoint: str = "https://api2.wer.plus/api/lanzpro"
    wer_api_method: str = "GET"
    wer_api_url_param: str = "url"
    wer_api_password_param: str = "pwd"
    wer_api_key: str = ""
    notification_template: str = "检测到网盘更新：{title}\n{url}"
    state_path: Path = DEFAULT_STATE_PATH
    watchers: list[WatcherConfig] = field(default_factory=list)
    notify_targets: list[NotifyTargetConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        watcher_ids: set[str] = set()
        for index, watcher in enumerate(self.watchers, start=1):
            watcher_id = str(watcher.id or "").strip()
            if not watcher_id:
                raise ValueError(f"watcher id must be non-empty (index {index})")
            if watcher_id in watcher_ids:
                raise ValueError(f"watcher ids must be unique: {watcher_id}")
            watcher_ids.add(watcher_id)
        if str(self.wer_api_method or "").upper() not in {"GET", "POST"}:
            raise ValueError("wer_api_method must be GET or POST")
        names: set[str] = set()
        for index, target in enumerate(self.notify_targets, start=1):
            name = str(target.name or "").strip()
            if not name:
                raise ValueError(f"notify target name must be non-empty (index {index})")
            if name in names:
                raise ValueError(f"notify target names must be unique (index {index})")
            names.add(name)


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _as_int(value: Any, fallback: int, minimum: int = 1, maximum: int = 86_400) -> int:
    if value is None or str(value).strip() == "":
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value}") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"integer must be between {minimum} and {maximum}: {parsed}")
    return parsed


def _as_float(value: Any, fallback: float, minimum: float = 0.1, maximum: float = 120.0) -> float:
    if value is None or str(value).strip() == "":
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid number value: {value}") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"number must be between {minimum} and {maximum}: {parsed}")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"config must be a JSON object: {path}")
    return data


def _watchers_from_env() -> list[dict[str, Any]]:
    raw = os.getenv("LANZOU_WATCH_URLS", "")
    urls = [item.strip() for item in raw.split(",") if item.strip()]
    return [
        {
            "id": f"watcher-{index}",
            "title": f"蓝奏网盘{index}",
            "url": url,
        }
        for index, url in enumerate(urls, start=1)
    ]


def _parse_watchers(raw: Any) -> list[WatcherConfig]:
    source = raw if isinstance(raw, list) else _watchers_from_env()
    watchers: list[WatcherConfig] = []
    ids: set[str] = set()
    for index, item in enumerate(source, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"watcher {index} must be an object")
        url = str(item.get("url") or "").strip()
        if not url:
            raise ValueError(f"watcher url must be non-empty (index {index})")
        watcher_id = str(item.get("id") or "").strip()
        if not watcher_id:
            raise ValueError(f"watcher id must be non-empty (index {index})")
        if watcher_id in ids:
            raise ValueError(f"watcher ids must be unique: {watcher_id}")
        ids.add(watcher_id)
        title = str(item.get("title") or item.get("name") or watcher_id).strip()
        watchers.append(
            WatcherConfig(
                id=watcher_id,
                title=title,
                url=url,
                password=str(item.get("password") or item.get("pwd") or "").strip(),
                enabled=_as_bool(item.get("enabled"), True),
                max_pages=_as_int(item.get("max_pages"), 20, 1, 100),
            )
        )
    return watchers


def _parse_notify_targets(raw: Any) -> list[NotifyTargetConfig]:
    if not isinstance(raw, list):
        return []
    targets: list[NotifyTargetConfig] = []
    names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"notify target name must be non-empty (index {index})")
        if name in names:
            raise ValueError(f"notify target names must be unique (index {index})")
        names.add(name)
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        targets.append(
            NotifyTargetConfig(
                name=name,
                url=url,
                enabled=_as_bool(item.get("enabled"), True),
                timeout_seconds=_as_float(item.get("timeout_seconds"), 8.0),
                headers={str(k): str(v) for k, v in headers.items()},
            )
        )
    return targets


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    raw = _load_json(config_path)
    state_path = Path(os.getenv("LANZOU_STATE_PATH") or raw.get("state_path") or DEFAULT_STATE_PATH).resolve()
    provider_order = raw.get("provider_order")
    if not isinstance(provider_order, list):
        provider_order = ["lanzou_web", "wer_api"]
    return AppConfig(
        host=str(os.getenv("LANZOU_MONITOR_HOST") or raw.get("host") or "127.0.0.1"),
        port=_as_int(os.getenv("LANZOU_MONITOR_PORT") or raw.get("port"), 6178, 1, 65535),
        scan_interval_seconds=_as_int(
            os.getenv("LANZOU_SCAN_INTERVAL_SECONDS") or raw.get("scan_interval_seconds"),
            300,
            5,
            86_400,
        ),
        scan_batch_size=_as_int(
            os.getenv("LANZOU_SCAN_BATCH_SIZE") or raw.get("scan_batch_size"),
            0,
            0,
            1_000,
        ),
        scan_batch_pause_seconds=_as_int(
            os.getenv("LANZOU_SCAN_BATCH_PAUSE_SECONDS") or raw.get("scan_batch_pause_seconds"),
            0,
            0,
            86_400,
        ),
        scan_on_start=_as_bool(raw.get("scan_on_start"), True),
        provider_order=[str(item).strip() for item in provider_order if str(item).strip()],
        wer_api_endpoint=str(raw.get("wer_api_endpoint") or "https://api2.wer.plus/api/lanzpro").strip(),
        wer_api_method=str(raw.get("wer_api_method") or "GET").strip().upper(),
        wer_api_url_param=str(raw.get("wer_api_url_param") or "url").strip(),
        wer_api_password_param=str(raw.get("wer_api_password_param") or "pwd").strip(),
        wer_api_key=str(os.getenv("LANZOU_API_KEY") or raw.get("wer_api_key") or raw.get("api_key") or "").strip(),
        notification_template=str(raw.get("notification_template") or "检测到网盘更新：{title}\n{url}"),
        state_path=state_path,
        watchers=_parse_watchers(raw.get("watchers")),
        notify_targets=_parse_notify_targets(raw.get("notify_targets")),
    )


def sanitized_config(config: AppConfig) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "scan_interval_seconds": config.scan_interval_seconds,
        "scan_batch_size": config.scan_batch_size,
        "scan_batch_pause_seconds": config.scan_batch_pause_seconds,
        "scan_on_start": config.scan_on_start,
        "provider_order": config.provider_order,
        "wer_api_endpoint": config.wer_api_endpoint,
        "wer_api_method": config.wer_api_method,
        "wer_api_url_param": config.wer_api_url_param,
        "wer_api_password_param": config.wer_api_password_param,
        "wer_api_key_configured": bool(config.wer_api_key),
        "notification_template": config.notification_template,
        "state_path": str(config.state_path),
        "watchers": [
            {
                "id": watcher.id,
                "title": watcher.title,
                "url": watcher.url,
                "password": "",
                "password_configured": bool(watcher.password),
                "enabled": watcher.enabled,
                "max_pages": watcher.max_pages,
            }
            for watcher in config.watchers
        ],
        "notify_targets": [
            {
                "name": target.name,
                "url": target.url,
                "enabled": target.enabled,
                "timeout_seconds": target.timeout_seconds,
                "headers": {key: "***" for key in target.headers},
            }
            for target in config.notify_targets
        ],
    }
