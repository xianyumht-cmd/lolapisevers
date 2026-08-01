from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from .management import APP_ENV_PATH, LOGS_DIR, _atomic_write_text, _backup_file


AUDIT_PATH = LOGS_DIR / "admin_audit.jsonl"
SERVICE_NAME = "LOLDataSystem"
_AUDIT_LOCK = threading.RLock()


def _audit_limits() -> tuple[int, int]:
    try:
        max_bytes = int(os.getenv("ADMIN_AUDIT_MAX_BYTES", str(5 * 1024 * 1024)))
    except ValueError:
        max_bytes = 5 * 1024 * 1024
    try:
        backups = int(os.getenv("ADMIN_AUDIT_BACKUPS", "5"))
    except ValueError:
        backups = 5
    return max(64 * 1024, min(max_bytes, 100 * 1024 * 1024)), max(1, min(backups, 20))


def _rotate_audit_if_needed(incoming_bytes: int) -> None:
    max_bytes, backups = _audit_limits()
    try:
        current_size = AUDIT_PATH.stat().st_size
    except OSError:
        current_size = 0
    if current_size + incoming_bytes <= max_bytes:
        return
    oldest = AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.{backups}")
    oldest.unlink(missing_ok=True)
    for index in range(backups - 1, 0, -1):
        source = AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.{index}")
        if source.exists():
            os.replace(source, AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.{index + 1}"))
    if AUDIT_PATH.exists():
        os.replace(AUDIT_PATH, AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.1"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_audit(
    *,
    action: str,
    ok: bool,
    client: str = "",
    method: str = "",
    path: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": uuid.uuid4().hex,
        "at": _utc_now(),
        "action": action,
        "ok": bool(ok),
        "client": client,
        "method": method,
        "path": path,
        "detail": detail or {},
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _AUDIT_LOCK:
        _rotate_audit_if_needed(len(line.encode("utf-8")))
        with AUDIT_PATH.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)


def read_audit(limit: int = 100) -> dict[str, Any]:
    count = max(1, min(1000, int(limit)))
    if not AUDIT_PATH.exists():
        return {"ok": True, "path": str(AUDIT_PATH), "events": []}
    with _AUDIT_LOCK, AUDIT_PATH.open("r", encoding="utf-8", errors="replace") as handle:
        lines = list(deque(handle, maxlen=count))
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return {"ok": True, "path": str(AUDIT_PATH), "events": events}


def _config_targets() -> dict[str, Path]:
    lanzou_path = Path(os.getenv("LANZOU_MONITOR_CONFIG") or DEFAULT_CONFIG_PATH).resolve()
    return {
        "main": APP_ENV_PATH.resolve(),
        "lanzou": lanzou_path,
    }


def list_config_backups() -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    for kind, target in _config_targets().items():
        parent = target.parent
        if not parent.exists():
            continue
        for path in parent.glob(f"{target.name}.bak.*"):
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "kind": kind,
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
    result.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"ok": True, "backups": result[:200]}


def _safe_backup_path(kind: str, backup_name: str) -> tuple[Path, Path]:
    targets = _config_targets()
    target = targets.get(kind)
    if target is None:
        raise ValueError("kind must be main or lanzou")
    name = Path(str(backup_name)).name
    expected_prefix = f"{target.name}.bak."
    if not name.startswith(expected_prefix):
        raise ValueError("invalid backup name")
    backup_path = (target.parent / name).resolve()
    if backup_path.parent != target.parent.resolve() or not backup_path.exists():
        raise FileNotFoundError("backup not found")
    return target, backup_path


def rollback_config(kind: str, backup_name: str) -> dict[str, Any]:
    target, backup_path = _safe_backup_path(kind, backup_name)
    content = backup_path.read_text(encoding="utf-8-sig")
    if kind == "lanzou":
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Lanzou backup must contain a JSON object")
    safety_backup = _backup_file(target)
    _atomic_write_text(target, content)
    result: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "restored_from": str(backup_path),
        "safety_backup": safety_backup,
        "restart_required": kind == "main",
    }
    if kind == "lanzou":
        result["config"] = load_config(target)
    return result


def windows_service_status(service_name: str = SERVICE_NAME) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "ok": False,
            "supported": False,
            "service": service_name,
            "state": "unsupported",
            "detail": "Windows service control is only available on Windows",
        }
    completed = subprocess.run(
        ["sc.exe", "query", service_name],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    output = (completed.stdout or completed.stderr).strip()
    state = "unknown"
    for candidate in ["RUNNING", "STOPPED", "START_PENDING", "STOP_PENDING", "PAUSED"]:
        if candidate in output:
            state = candidate.lower()
            break
    return {
        "ok": completed.returncode == 0,
        "supported": True,
        "service": service_name,
        "state": state,
        "detail": output[-4000:],
    }


def schedule_windows_service_restart(service_name: str = SERVICE_NAME, delay_seconds: int = 3) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Windows service restart is only available on Windows")
    delay = max(2, min(30, int(delay_seconds)))
    escaped_name = service_name.replace("'", "''")
    command = (
        f"Start-Sleep -Seconds {delay}; "
        f"Restart-Service -Name '{escaped_name}' -Force -ErrorAction Stop"
    )
    creation_flags = 0
    for flag_name in ["CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"]:
        creation_flags |= int(getattr(subprocess, flag_name, 0))
    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return {
        "ok": True,
        "service": service_name,
        "scheduled": True,
        "delay_seconds": delay,
        "launcher_pid": process.pid,
        "message": "服务重启已安排，控制台连接会暂时中断。",
    }
