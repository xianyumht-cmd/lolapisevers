from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from services.target_file_watch_service import (
    STATE_VERSION,
    TargetFileWatchError,
    TargetFileWatchService,
    _atomic_json_write,
    _state_path,
)


class SafeTargetFileWatchService(TargetFileWatchService):
    """Production wrapper that never guesses after persisted state corruption.

    The base service contains the feature state machine. This wrapper adds the
    production invariant that a malformed/unreadable state file cannot be
    silently replaced with an empty state, because that could lose delivery
    history and allow a duplicate upload. Recovery is explicit through the
    authenticated rebaseline action, which quarantines the damaged state first.
    """

    def __init__(self) -> None:
        self.state_healthy = True
        self.state_error_code = ""
        self.state_quarantine_file = ""
        super().__init__()

    def _load_state(self) -> None:
        path = _state_path()
        if not path.exists():
            self._state = self._empty_state()
            self.state_healthy = True
            self.state_error_code = ""
            self.state_quarantine_file = ""
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict) or int(raw.get("version") or 0) != STATE_VERSION:
                raise ValueError("invalid state")
            self._state = {**self._empty_state(), **raw}
            self.state_healthy = True
            self.state_error_code = ""
            self.state_quarantine_file = ""
        except Exception as exc:
            self._state = self._empty_state()
            self.state_healthy = False
            self.state_error_code = "target_file_watch_state_corrupt"
            self.logger.error(
                "target file state is unreadable; monitoring stopped to prevent duplicate delivery: %s",
                type(exc).__name__,
            )

    def _save_state(self) -> None:
        if not self.state_healthy:
            raise TargetFileWatchError("target_file_watch_state_unavailable")
        _atomic_json_write(_state_path(), self._state)

    def status(self) -> dict[str, Any]:
        result = super().status()
        result["state_healthy"] = self.state_healthy
        result["state_error_code"] = self.state_error_code
        result["state_quarantine_file"] = self.state_quarantine_file
        if not self.state_healthy:
            result["ok"] = False
            result["running"] = False
        return result

    async def check_once(self) -> dict[str, Any]:
        self._load_state()
        if not self.state_healthy:
            raise TargetFileWatchError("target_file_watch_state_unavailable")
        return await super().check_once()

    def rebaseline(self) -> dict[str, Any]:
        path = _state_path()
        if not self.state_healthy and path.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            quarantine = path.with_name(f"{path.name}.corrupt-{stamp}-{os.getpid()}")
            path.replace(quarantine)
            self.state_quarantine_file = quarantine.name
        self.state_healthy = True
        self.state_error_code = ""
        self._state = self._empty_state()
        self._state["source_url"] = self._config.source_url
        self._save_state()
        return self.status()


target_file_watch_service = SafeTargetFileWatchService()
