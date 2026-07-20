from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import DEFAULT_CONFIG_PATH, DEFAULT_STATE_PATH, AppConfig, load_config
from .state_recovery import recover_state_file


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ENV_PATH = PROJECT_ROOT / "ops" / "app_env.local.ps1"
APP_ENV_EXAMPLE_PATH = PROJECT_ROOT / "ops" / "app_env.example.ps1"
LOGS_DIR = PROJECT_ROOT / "logs"

MAIN_CONFIG_FIELDS: list[dict[str, Any]] = [
    {"key": "APP_HOST", "label": "主接口监听地址", "section": "主接口", "type": "text"},
    {"key": "APP_PORT", "label": "主接口端口", "section": "主接口", "type": "int", "min": 1, "max": 65535},
    {"key": "PYTHONIOENCODING", "label": "Python 输出编码", "section": "主接口", "type": "text"},
    {"key": "CACHE_SECONDS", "label": "通用缓存秒数", "section": "缓存", "type": "int", "min": 1, "max": 86400},
    {"key": "SHARD_CACHE_SECONDS", "label": "云顶合集缓存秒数", "section": "缓存", "type": "int", "min": 1, "max": 86400},
    {"key": "ARAM_AUGMENT_CACHE_SECONDS", "label": "大乱斗缓存秒数", "section": "缓存", "type": "int", "min": 1, "max": 86400},
    {"key": "MYSQL_HOST", "label": "MySQL 地址", "section": "MySQL", "type": "text"},
    {"key": "MYSQL_PORT", "label": "MySQL 端口", "section": "MySQL", "type": "int", "min": 1, "max": 65535},
    {"key": "MYSQL_USER", "label": "MySQL 用户", "section": "MySQL", "type": "text"},
    {"key": "MYSQL_PASSWORD", "label": "MySQL 密码", "section": "MySQL", "type": "secret"},
    {"key": "MYSQL_DATABASE", "label": "MySQL 数据库", "section": "MySQL", "type": "text"},
    {"key": "SO1_USERNAME", "label": "SO1 用户名", "section": "SO1", "type": "secret"},
    {"key": "SO1_PASSWORD", "label": "SO1 密码", "section": "SO1", "type": "secret"},
    {"key": "SO1_HEADLESS", "label": "SO1 无头模式", "section": "SO1", "type": "bool"},
    {"key": "SO1_TIMEOUT_MS", "label": "SO1 超时毫秒", "section": "SO1", "type": "int", "min": 1000, "max": 300000},
    {"key": "SO1_MAX_CONCURRENT_PAGES", "label": "SO1 最大并发页面", "section": "SO1", "type": "int", "min": 1, "max": 32},
    {"key": "PLAYWRIGHT_BROWSERS_PATH", "label": "Playwright 浏览器目录", "section": "运行环境", "type": "text"},
    {"key": "KEEPALIVE_BASE_URL", "label": "保活接口地址", "section": "保活", "type": "text"},
    {"key": "KEEPALIVE_TEST_NAME", "label": "保活测试账号", "section": "保活", "type": "text"},
    {"key": "KEEPALIVE_TEST_REGION", "label": "保活测试大区", "section": "保活", "type": "text"},
]

_FIELD_BY_KEY = {field["key"]: field for field in MAIN_CONFIG_FIELDS}
_ENV_LINE_RE = re.compile(r"^(?P<prefix>\s*\$env:)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<middle>\s*=\s*)(?P<value>.*?)(?P<suffix>\s*)$")

LOG_FILES = {
    "main_stdout": LOGS_DIR / "service.stdout.log",
    "main_stderr": LOGS_DIR / "service.stderr.log",
    "lanzou_stdout": LOGS_DIR / "lanzou_monitor.stdout.log",
    "lanzou_stderr": LOGS_DIR / "lanzou_monitor.stderr.log",
    "keepalive": LOGS_DIR / "keepalive.log",
    "server": LOGS_DIR / "server.log",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _backup_file(path: Path) -> str:
    if not path.exists():
        return ""
    backup_path = path.with_name(f"{path.name}.bak.{_timestamp()}")
    backup_path.write_bytes(path.read_bytes())
    return str(backup_path)


def _parse_ps_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('`"', '"').replace('``', '`')
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _format_ps_value(value: Any) -> str:
    text = str(value)
    escaped = text.replace('`', '``').replace('"', '`"')
    return f'"{escaped}"'


def _read_env_source() -> tuple[str, Path]:
    if APP_ENV_PATH.exists():
        return APP_ENV_PATH.read_text(encoding="utf-8-sig"), APP_ENV_PATH
    if APP_ENV_EXAMPLE_PATH.exists():
        return APP_ENV_EXAMPLE_PATH.read_text(encoding="utf-8-sig"), APP_ENV_EXAMPLE_PATH
    return "# lolapisevers local environment\n", APP_ENV_PATH


def _parse_env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _ENV_LINE_RE.match(line)
        if match:
            values[match.group("key")] = _parse_ps_value(match.group("value"))
    return values


def read_main_config() -> dict[str, Any]:
    text, source = _read_env_source()
    file_values = _parse_env_values(text)
    fields: list[dict[str, Any]] = []
    for spec in MAIN_CONFIG_FIELDS:
        item = dict(spec)
        value = file_values.get(spec["key"], os.getenv(spec["key"], ""))
        if spec["type"] == "secret":
            item["value"] = ""
            item["configured"] = bool(str(value).strip() and str(value).strip() != "CHANGE_ME")
        elif spec["type"] == "bool":
            item["value"] = str(value).strip().lower() not in {"0", "false", "no", "off", ""}
        else:
            item["value"] = value
        fields.append(item)
    return {
        "ok": True,
        "path": str(APP_ENV_PATH),
        "source": str(source),
        "exists": APP_ENV_PATH.exists(),
        "restart_required": True,
        "fields": fields,
    }


def _normalize_main_value(spec: dict[str, Any], value: Any) -> str:
    field_type = spec["type"]
    if field_type == "bool":
        if isinstance(value, bool):
            return "1" if value else "0"
        return "0" if str(value).strip().lower() in {"0", "false", "no", "off", ""} else "1"
    if field_type == "int":
        parsed = int(value)
        minimum = int(spec.get("min", -2**31))
        maximum = int(spec.get("max", 2**31 - 1))
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{spec['key']} must be between {minimum} and {maximum}")
        return str(parsed)
    text = str(value).strip()
    if spec["key"] in {"APP_HOST", "MYSQL_HOST"} and not text:
        raise ValueError(f"{spec['key']} cannot be empty")
    return text


def update_main_config(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("main config patch must be an object")
    source_text, _source = _read_env_source()
    current_values = _parse_env_values(source_text)
    normalized: dict[str, str] = {}
    for key, value in patch.items():
        spec = _FIELD_BY_KEY.get(key)
        if spec is None:
            raise ValueError(f"unsupported main config field: {key}")
        if spec["type"] == "secret" and (value is None or str(value).strip() == ""):
            continue
        normalized[key] = _normalize_main_value(spec, value)

    lines = source_text.splitlines()
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        match = _ENV_LINE_RE.match(line)
        if not match:
            output.append(line)
            continue
        key = match.group("key")
        if key not in normalized:
            output.append(line)
            continue
        output.append(f"{match.group('prefix')}{key}{match.group('middle')}{_format_ps_value(normalized[key])}")
        seen.add(key)

    missing = [key for key in normalized if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Added by lolapisevers WebUI")
        for key in missing:
            output.append(f"$env:{key} = {_format_ps_value(normalized[key])}")

    backup_path = _backup_file(APP_ENV_PATH)
    _atomic_write_text(APP_ENV_PATH, "\n".join(output))
    return {
        "ok": True,
        "message": "主接口配置已保存，重启 LOLDataSystem 后生效。",
        "backup_path": backup_path,
        "config": read_main_config(),
    }


def read_lanzou_config() -> dict[str, Any]:
    path = Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("lanzou config must be a JSON object")
    return data


def _as_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _validate_http_url(value: str, name: str, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if allow_empty and not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http or https URL")
    return text


def update_lanzou_config(patch: dict[str, Any]) -> tuple[AppConfig, str]:
    if not isinstance(patch, dict):
        raise ValueError("lanzou config patch must be an object")
    current = read_lanzou_config()

    if "host" in patch:
        host = str(patch["host"]).strip()
        if not host:
            raise ValueError("host cannot be empty")
        current["host"] = host
    if "port" in patch:
        current["port"] = _as_int(patch["port"], "port", 1, 65535)
    for key, minimum, maximum in [
        ("scan_interval_seconds", 5, 86400),
        ("scan_batch_size", 0, 1000),
        ("scan_batch_pause_seconds", 0, 86400),
    ]:
        if key in patch:
            current[key] = _as_int(patch[key], key, minimum, maximum)
    if "scan_on_start" in patch:
        current["scan_on_start"] = bool(patch["scan_on_start"])
    if "provider_order" in patch:
        if not isinstance(patch["provider_order"], list):
            raise ValueError("provider_order must be a list")
        current["provider_order"] = [str(item).strip() for item in patch["provider_order"] if str(item).strip()]
    for key in ["wer_api_method", "wer_api_url_param", "wer_api_password_param", "notification_template"]:
        if key in patch:
            current[key] = str(patch[key]).strip()
    if "wer_api_endpoint" in patch:
        current["wer_api_endpoint"] = _validate_http_url(patch["wer_api_endpoint"], "wer_api_endpoint")
    if "wer_api_key" in patch and str(patch["wer_api_key"] or "").strip():
        current["wer_api_key"] = str(patch["wer_api_key"]).strip()
    if "state_path" in patch:
        state_path = str(patch["state_path"] or "").strip()
        if not state_path:
            raise ValueError("state_path cannot be empty")
        current["state_path"] = state_path

    if "watchers" in patch:
        if not isinstance(patch["watchers"], list):
            raise ValueError("watchers must be a list")
        watchers: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, raw in enumerate(patch["watchers"], start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"watcher {index} must be an object")
            watcher_id = str(raw.get("id") or "").strip()
            if not watcher_id or watcher_id in ids:
                raise ValueError(f"watcher id is empty or duplicated: {watcher_id}")
            ids.add(watcher_id)
            item = {
                "id": watcher_id,
                "title": str(raw.get("title") or watcher_id).strip(),
                "url": _validate_http_url(raw.get("url"), f"watcher {watcher_id} url"),
                "password": str(raw.get("password") or "").strip(),
                "enabled": raw.get("enabled") is not False,
                "max_pages": _as_int(raw.get("max_pages") or 20, f"watcher {watcher_id} max_pages", 1, 100),
            }
            watchers.append(item)
        current["watchers"] = watchers

    if "notify_targets" in patch:
        if not isinstance(patch["notify_targets"], list):
            raise ValueError("notify_targets must be a list")
        targets: list[dict[str, Any]] = []
        for index, raw in enumerate(patch["notify_targets"], start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"notify target {index} must be an object")
            headers = raw.get("headers") or {}
            if not isinstance(headers, dict):
                raise ValueError(f"notify target {index} headers must be an object")
            targets.append(
                {
                    "name": str(raw.get("name") or f"target-{index}").strip(),
                    "enabled": raw.get("enabled") is not False,
                    "url": _validate_http_url(raw.get("url"), f"notify target {index} url"),
                    "timeout_seconds": float(raw.get("timeout_seconds") or 8.0),
                    "headers": {str(key): str(value) for key, value in headers.items()},
                }
            )
        current["notify_targets"] = targets

    path = Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    backup_path = _backup_file(path)
    _atomic_write_text(path, json.dumps(current, ensure_ascii=False, indent=2))
    return load_config(path), backup_path


def list_logs() -> dict[str, Any]:
    items = []
    for name, path in LOG_FILES.items():
        stat = path.stat() if path.exists() else None
        items.append(
            {
                "name": name,
                "path": str(path),
                "exists": stat is not None,
                "size_bytes": stat.st_size if stat else 0,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat() if stat else "",
            }
        )
    return {"ok": True, "logs": items}


def read_log(name: str, lines: int = 200, search: str = "") -> dict[str, Any]:
    path = LOG_FILES.get(name)
    if path is None:
        raise ValueError(f"unknown log: {name}")
    count = max(1, min(5000, int(lines)))
    if not path.exists():
        return {"ok": True, "name": name, "path": str(path), "content": "", "exists": False}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        tail = deque(handle, maxlen=count)
    content_lines = list(tail)
    needle = search.strip().lower()
    if needle:
        content_lines = [line for line in content_lines if needle in line.lower()]
    return {
        "ok": True,
        "name": name,
        "path": str(path),
        "content": "".join(content_lines),
        "exists": True,
    }


def fetch_openapi(service: str) -> dict[str, Any]:
    base_url = "http://127.0.0.1:5001" if service == "main" else "http://127.0.0.1:6178"
    response = requests.get(f"{base_url}/openapi.json", timeout=5)
    response.raise_for_status()
    return response.json()


def invoke_local_api(payload: dict[str, Any]) -> dict[str, Any]:
    service = str(payload.get("service") or "main")
    if service not in {"main", "lanzou"}:
        raise ValueError("service must be main or lanzou")
    method = str(payload.get("method") or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported HTTP method")
    path = str(payload.get("path") or "").strip()
    if not path.startswith("/") or "://" in path or ".." in path:
        raise ValueError("path must be a safe relative API path")
    if path == "/admin/invoke":
        raise ValueError("recursive invocation is not allowed")
    query = payload.get("query") or {}
    body = payload.get("json")
    if not isinstance(query, dict):
        raise ValueError("query must be an object")
    timeout = max(1.0, min(120.0, float(payload.get("timeout") or 30.0)))
    base_url = "http://127.0.0.1:5001" if service == "main" else "http://127.0.0.1:6178"
    started = time.time()
    response = requests.request(method, f"{base_url}{path}", params=query, json=body, timeout=timeout)
    elapsed_ms = int((time.time() - started) * 1000)
    content_type = response.headers.get("content-type", "")
    result: dict[str, Any] = {
        "ok": response.ok,
        "status_code": response.status_code,
        "content_type": content_type,
        "elapsed_ms": elapsed_ms,
        "headers": {key: value for key, value in response.headers.items()},
    }
    if "application/json" in content_type:
        try:
            result["json"] = response.json()
        except ValueError:
            result["text"] = response.text[:1_000_000]
    elif content_type.startswith("image/") or "image/svg+xml" in content_type:
        if len(response.content) > 5_000_000:
            raise ValueError("response image is larger than 5 MB")
        result["base64"] = base64.b64encode(response.content).decode("ascii")
    else:
        result["text"] = response.text[:1_000_000]
    return result


def _tcp_check(host: str, port: int, timeout: float = 0.8) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "connected"
    except OSError as exc:
        return False, str(exc)


def _json_file_check(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return False, "JSON root is not an object"
        return True, "valid"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def run_diagnostics() -> dict[str, Any]:
    config_path = Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    try:
        config = load_config(config_path)
        state_path = config.state_path
    except Exception:
        config = None
        state_path = DEFAULT_STATE_PATH.resolve()

    items: list[dict[str, Any]] = []
    for name, host, port in [
        ("main_api_port", "127.0.0.1", 5001),
        ("lanzou_port", "127.0.0.1", 6178),
        ("mysql_port", "127.0.0.1", 3306),
    ]:
        ok, detail = _tcp_check(host, port)
        items.append({"name": name, "ok": ok, "detail": detail})

    for name, path in [("lanzou_config", config_path), ("lanzou_state", state_path)]:
        ok, detail = _json_file_check(path)
        items.append({"name": name, "ok": ok, "detail": detail, "path": str(path)})

    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    items.append({"name": "venv_python", "ok": venv_python.exists(), "detail": str(venv_python)})
    playwright_path = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH") or PROJECT_ROOT / "ms-playwright")
    items.append({"name": "playwright_path", "ok": playwright_path.exists(), "detail": str(playwright_path)})
    items.append({"name": "main_env", "ok": APP_ENV_PATH.exists(), "detail": str(APP_ENV_PATH)})

    service_detail = "unsupported on this platform"
    service_ok = False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["sc.exe", "query", "LOLDataSystem"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            service_detail = (completed.stdout or completed.stderr).strip()[-2000:]
            service_ok = "RUNNING" in completed.stdout
        except Exception as exc:
            service_detail = str(exc)
    items.append({"name": "windows_service", "ok": service_ok, "detail": service_detail})

    return {"ok": all(item["ok"] for item in items if item["name"] != "windows_service") and service_ok, "items": items}


def repair_state() -> dict[str, Any]:
    config_path = Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    config = load_config(config_path)
    return recover_state_file(config.state_path)
