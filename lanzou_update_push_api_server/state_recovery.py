from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_state() -> dict[str, Any]:
    return {"version": 1, "snapshots": {}, "events": [], "last_scan": {}}


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _backup_corrupt_file(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.with_name(f"{path.name}.bad.{stamp}")
    try:
        path.replace(backup_path)
    except OSError:
        shutil.copy2(path, backup_path)
        path.unlink()
    return backup_path


def recover_state_file(path: Path) -> dict[str, Any]:
    """Validate a persisted monitor state file and recover it when unreadable.

    Corrupt or empty files are moved aside with a timestamped ``.bad`` suffix,
    then replaced atomically with a clean default state. The backup is never
    deleted automatically.
    """

    resolved = path.resolve()
    if not resolved.exists():
        return {
            "ok": True,
            "action": "missing",
            "path": str(resolved),
            "backup_path": "",
            "error": "",
        }

    try:
        with resolved.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("state file must contain a JSON object")
        return {
            "ok": True,
            "action": "valid",
            "path": str(resolved),
            "backup_path": "",
            "error": "",
        }
    except (json.JSONDecodeError, UnicodeError, ValueError, OSError) as exc:
        backup_path = _backup_corrupt_file(resolved)
        _write_json_atomic(resolved, default_state())
        return {
            "ok": True,
            "action": "recovered",
            "path": str(resolved),
            "backup_path": str(backup_path),
            "error": f"{type(exc).__name__}: {exc}",
        }
