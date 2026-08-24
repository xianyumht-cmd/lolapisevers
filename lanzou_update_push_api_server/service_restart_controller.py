from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .management import LOGS_DIR


SERVICE_NAME = "LOLDataSystem"
RESTART_STATE_PATH = LOGS_DIR / "service_restart_state.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _read_restart_state() -> dict[str, Any]:
    try:
        data = json.loads(RESTART_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _query_service(service_name: str = SERVICE_NAME) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "ok": False,
            "supported": False,
            "service": service_name,
            "state": "unsupported",
            "process_id": 0,
            "detail": "Windows service control is only available on Windows",
        }
    completed = subprocess.run(
        ["sc.exe", "queryex", service_name],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    state = "unknown"
    for candidate in ["RUNNING", "STOPPED", "START_PENDING", "STOP_PENDING", "PAUSED"]:
        if candidate in output:
            state = candidate.lower()
            break
    process_id = 0
    match = re.search(r"(?im)^\s*PID\s*:\s*(\d+)\s*$", output)
    if match:
        process_id = int(match.group(1))
    return {
        "ok": completed.returncode == 0,
        "supported": True,
        "service": service_name,
        "state": state,
        "process_id": process_id,
        "detail": output[-4000:],
    }


def _parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reconcile_restart_verification(service: dict[str, Any]) -> dict[str, Any]:
    marker = _read_restart_state()
    if not marker:
        return {}
    status = str(marker.get("status") or "").lower()
    if status != "scheduled":
        return marker

    before_pid = int(marker.get("before_pid") or 0)
    after_pid = int(service.get("process_id") or 0)
    running = str(service.get("state") or "").lower() == "running"
    changed = after_pid > 0 and (before_pid <= 0 or after_pid != before_pid)
    if running and changed:
        marker.update(
            {
                "status": "verified",
                "verified_at": _utc_now(),
                "after_pid": after_pid,
                "message": f"服务重启已验证：PID {before_pid or '-'} → {after_pid}",
            }
        )
        _atomic_write_json(RESTART_STATE_PATH, marker)
        return marker

    requested_at = _parse_iso(marker.get("requested_at"))
    age = (
        max(0.0, (datetime.now(timezone.utc) - requested_at).total_seconds())
        if requested_at
        else 0.0
    )
    marker["age_seconds"] = round(age, 1)
    if age >= 60:
        marker.update(
            {
                "status": "unverified",
                "checked_at": _utc_now(),
                "after_pid": after_pid,
                "message": "60 秒内未观察到服务 PID 更换；不能确认本次重启成功。",
            }
        )
        _atomic_write_json(RESTART_STATE_PATH, marker)
    return marker


def windows_service_status(service_name: str = SERVICE_NAME) -> dict[str, Any]:
    service = _query_service(service_name)
    if service.get("supported") is False:
        service["restart_verification"] = {}
        return service
    service["restart_verification"] = _reconcile_restart_verification(service)
    return service


def schedule_windows_service_restart(
    service_name: str = SERVICE_NAME,
    delay_seconds: int = 3,
) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Windows service restart is only available on Windows")
    delay = max(2, min(30, int(delay_seconds)))
    before = _query_service(service_name)
    if not before.get("ok"):
        raise RuntimeError("无法读取 Windows 服务状态，拒绝安排未验证重启")
    before_pid = int(before.get("process_id") or 0)
    request_id = uuid.uuid4().hex
    marker = {
        "request_id": request_id,
        "status": "scheduled",
        "service": service_name,
        "requested_at": _utc_now(),
        "before_pid": before_pid,
        "delay_seconds": delay,
        "message": "重启命令已安排，等待服务 PID 更换后才会标记为成功。",
    }
    _atomic_write_json(RESTART_STATE_PATH, marker)

    escaped_name = service_name.replace("'", "''")
    command = (
        f"Start-Sleep -Seconds {delay}; "
        f"Restart-Service -Name '{escaped_name}' -Force -ErrorAction Stop"
    )
    creation_flags = 0
    for flag_name in ["CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"]:
        creation_flags |= int(getattr(subprocess, flag_name, 0))
    try:
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
    except Exception:
        marker.update(
            {
                "status": "launch_failed",
                "checked_at": _utc_now(),
                "message": "独立 PowerShell 重启进程启动失败。",
            }
        )
        _atomic_write_json(RESTART_STATE_PATH, marker)
        raise

    marker["launcher_pid"] = int(process.pid)
    _atomic_write_json(RESTART_STATE_PATH, marker)
    return {
        "ok": True,
        "service": service_name,
        "scheduled": True,
        "verified": False,
        "request_id": request_id,
        "before_pid": before_pid,
        "delay_seconds": delay,
        "launcher_pid": process.pid,
        "message": "重启已安排；WebUI 将等待 PID 变化后再确认成功。",
    }
