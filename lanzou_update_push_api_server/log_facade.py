from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"


def _pick_existing(primary: Path, legacy: Path | None = None) -> Path:
    if primary.exists() or legacy is None:
        return primary
    return legacy


def log_files() -> dict[str, Path]:
    return {
        "supervisor_stdout": _pick_existing(
            LOGS_DIR / "supervisor.stdout.log",
            LOGS_DIR / "service.stdout.log",
        ),
        "supervisor_stderr": _pick_existing(
            LOGS_DIR / "supervisor.stderr.log",
            LOGS_DIR / "service.stderr.log",
        ),
        "main_stdout": LOGS_DIR / "main_api.stdout.log",
        "main_stderr": LOGS_DIR / "main_api.stderr.log",
        "lanzou_stdout": LOGS_DIR / "lanzou_monitor.stdout.log",
        "lanzou_stderr": LOGS_DIR / "lanzou_monitor.stderr.log",
        "keepalive": LOGS_DIR / "keepalive.log",
        "server": LOGS_DIR / "server.log",
    }


def list_logs() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for name, path in log_files().items():
        exists = path.exists()
        items.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else 0,
            }
        )
    return {"ok": True, "logs": items}


def read_log(name: str, lines: int = 200, search: str = "") -> dict[str, Any]:
    path = log_files().get(name)
    if path is None:
        raise ValueError(f"unknown log name: {name}")

    limit = max(1, min(5000, int(lines)))
    if not path.exists():
        return {
            "ok": True,
            "name": name,
            "path": str(path),
            "exists": False,
            "content": "",
        }

    needle = search.casefold().strip()
    selected: deque[str] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if needle and needle not in line.casefold():
                continue
            selected.append(line.rstrip("\r\n"))

    return {
        "ok": True,
        "name": name,
        "path": str(path),
        "exists": True,
        "content": "\n".join(selected),
    }
