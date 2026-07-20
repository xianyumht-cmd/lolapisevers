from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from .config import AppConfig, DEFAULT_CONFIG_PATH, load_config, sanitized_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ENV_PATH = PROJECT_ROOT / "ops" / "app_env.local.ps1"


FUNCTIONS = [
    {
        "name": "健康检查",
        "method": "GET",
        "path": "/health",
        "description": "查看主接口、MySQL、SO1 浏览器状态。",
        "example": "http://127.0.0.1:5001/health",
    },
    {
        "name": "跨区战绩查询",
        "method": "GET",
        "path": "/cross_query",
        "description": "按召唤师名称和大区查询战绩，支持 pretty/raw/image/svg 输出。",
        "example": "http://127.0.0.1:5001/cross_query?name=DarkThesoul%2357947&region=GZ100&output=pretty",
    },
    {
        "name": "SO1 会话初始化",
        "method": "POST",
        "path": "/cross_session_init",
        "description": "手动初始化 SO1 会话，主要用于登录态维护。",
        "example": "http://127.0.0.1:5001/cross_session_init?wait_seconds=180",
    },
    {
        "name": "查封号",
        "method": "GET",
        "path": "/lolban / /api/v2/lolban",
        "description": "按 QQ 查询封号信息，支持 text/json。",
        "example": "http://127.0.0.1:5001/api/v2/lolban?qq=123456&output=json",
    },
    {
        "name": "云顶合集查询",
        "method": "GET",
        "path": "/shard_query",
        "description": "按英雄名称查询云顶合集，支持 image/json。",
        "example": "http://127.0.0.1:5001/shard_query?hero=亚索&output=image",
    },
    {
        "name": "大乱斗强化符文",
        "method": "GET",
        "path": "/aram_augments",
        "description": "按英雄名称查询大乱斗强化符文，支持 image/json。",
        "example": "http://127.0.0.1:5001/aram_augments?hero=亚索&output=image",
    },
    {
        "name": "蓝奏监控健康",
        "method": "GET",
        "path": "/health",
        "description": "查看蓝奏监控服务状态、监控数量、扫描节奏。",
        "example": "http://192.168.3.100:6178/health",
        "service": "lanzou",
    },
    {
        "name": "蓝奏监控列表",
        "method": "GET",
        "path": "/watchers",
        "description": "查看所有蓝奏监控链接和最近快照。",
        "example": "http://192.168.3.100:6178/watchers",
        "service": "lanzou",
    },
    {
        "name": "蓝奏单链接扫描",
        "method": "POST",
        "path": "/scan?watcher_id=ID&notify=false",
        "description": "手动扫描指定监控项。建议只扫单个 watcher，避免一次请求全部链接。",
        "example": "http://192.168.3.100:6178/scan?watcher_id=nav-029-jntm&notify=false",
        "service": "lanzou",
    },
    {
        "name": "蓝奏测试推送",
        "method": "POST",
        "path": "/notify/test",
        "description": "向 SnowLuma 插件端发送一条测试更新。",
        "example": "http://192.168.3.100:6178/notify/test",
        "service": "lanzou",
    },
]


def _config_path() -> Path:
    return Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()


def _mask_secret(value: Any) -> str:
    return "已配置" if str(value or "").strip() else "未配置"


def _dataclass_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return dict(value or {})


def _main_config_summary() -> dict[str, Any]:
    try:
        from core.config import load_config as load_main_config

        config = load_main_config()
        return {
            "ok": True,
            "values": {
                "app_host": config.app_host,
                "app_port": config.app_port,
                "cache_seconds": config.cache_seconds,
                "shard_cache_seconds": config.shard_cache_seconds,
                "aram_augment_cache_seconds": config.aram_augment_cache_seconds,
                "shard_data_url": config.shard_data_url,
                "shard_hero_url": config.shard_hero_url,
                "mysql_host": config.mysql_host,
                "mysql_port": config.mysql_port,
                "mysql_user": config.mysql_user,
                "mysql_password": _mask_secret(config.mysql_password),
                "mysql_database": config.mysql_database,
                "so1_username": _mask_secret(config.so1_username),
                "so1_password": _mask_secret(config.so1_password),
                "so1_headless": config.so1_headless,
                "so1_timeout_ms": config.so1_timeout_ms,
            },
            "source": str(APP_ENV_PATH),
            "restart_required": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "source": str(APP_ENV_PATH)}


def _fetch_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout, headers={"accept": "application/json"})
    text = response.text
    try:
        data = response.json()
    except ValueError:
        data = {"raw": text}
    if not response.ok:
        return {"ok": False, "status_code": response.status_code, "error": data.get("error") or text}
    if isinstance(data, dict):
        data.setdefault("ok", True)
        return data
    return {"ok": True, "data": data}


def _mask_url_secret(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in list(query):
        if key.lower() in {"token", "key", "auth", "password"}:
            query[key] = ["***"]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment))


def _main_health() -> dict[str, Any]:
    try:
        return _fetch_json("http://127.0.0.1:5001/health")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _status_url_from_notify_target(config: AppConfig) -> str:
    for target in config.notify_targets:
        if not target.enabled:
            continue
        parsed = urlparse(target.url)
        if not parsed.scheme or not parsed.netloc:
            continue
        query = parse_qs(parsed.query)
        status_query = {}
        if query.get("token"):
            status_query["token"] = query["token"][0]
        return urlunparse((parsed.scheme, parsed.netloc, "/api/status", "", urlencode(status_query), ""))
    return "http://192.168.3.89:6108/api/status?token=gg6108"


def _plugin_status(config: AppConfig) -> dict[str, Any]:
    url = _status_url_from_notify_target(config)
    try:
        data = _fetch_json(url)
        return {"ok": data.get("ok") is not False and "error" not in data, "url": _mask_url_secret(url), "data": data}
    except Exception as exc:
        return {"ok": False, "url": _mask_url_secret(url), "error": str(exc)}


def build_admin_overview(config: AppConfig, service_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "projectRoot": str(PROJECT_ROOT),
        "configPath": str(_config_path()),
        "mainApi": {
            "baseUrl": "http://127.0.0.1:5001",
            "health": _main_health(),
            "config": _main_config_summary(),
            "functions": FUNCTIONS,
        },
        "lanzou": {
            "baseUrl": f"http://{config.host}:{config.port}",
            "health": service_status,
            "config": sanitized_config(config),
        },
        "plugin": _plugin_status(config),
    }


def read_lanzou_config_file() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("lanzou config must be a JSON object")
    return data


def _clean_watchers(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    watchers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        watcher_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not watcher_id or not url:
            continue
        watchers.append(
            {
                "id": watcher_id,
                "title": str(item.get("title") or watcher_id).strip(),
                "url": url,
                "password": str(item.get("password") or "").strip(),
                "enabled": item.get("enabled") is not False,
                "max_pages": max(1, min(100, int(item.get("max_pages") or 20))),
            }
        )
    return watchers


def _clean_notify_targets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    targets = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        targets.append(
            {
                "name": str(item.get("name") or "target").strip(),
                "enabled": item.get("enabled") is not False,
                "url": url,
                "timeout_seconds": max(0.1, min(120.0, float(item.get("timeout_seconds") or 8.0))),
                "headers": {str(key): str(value) for key, value in headers.items()},
            }
        )
    return targets


def update_lanzou_config_file(patch: dict[str, Any]) -> AppConfig:
    current = read_lanzou_config_file()
    for key in ["scan_interval_seconds", "scan_batch_size", "scan_batch_pause_seconds"]:
        if key in patch:
            current[key] = int(patch[key])
    for key in ["scan_on_start"]:
        if key in patch:
            current[key] = bool(patch[key])
    for key in ["notification_template", "wer_api_method", "wer_api_endpoint", "wer_api_url_param", "wer_api_password_param"]:
        if key in patch:
            current[key] = str(patch[key]).strip()
    if "provider_order" in patch and isinstance(patch["provider_order"], list):
        current["provider_order"] = [str(item).strip() for item in patch["provider_order"] if str(item).strip()]
    if "watchers" in patch:
        current["watchers"] = _clean_watchers(patch["watchers"])
    if "notify_targets" in patch:
        current["notify_targets"] = _clean_notify_targets(patch["notify_targets"])

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(path)
    return load_config(path)
