from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any

from services.target_file_watch_directory import DirectoryLanzouResolver, check_directory_once
from services.target_file_watch_service import (
    STATE_VERSION,
    TargetFileWatchConfig,
    TargetFileWatchError,
    TargetFileWatchService,
    _atomic_json_write,
    _config_path,
    _stable_url,
    _state_path,
    normalize_config,
)


class SafeTargetFileWatchService(TargetFileWatchService):
    """Production target-file watcher with fail-safe persisted state handling.

    The legacy Lanzou monitor remains untouched. This service reuses only the
    provider/parser layer and keeps an independent directory snapshot baseline.
    """

    def __init__(self) -> None:
        self.state_healthy = True
        self.state_error_code = ""
        self.state_quarantine_file = ""
        self.directory_resolver = DirectoryLanzouResolver()
        super().__init__()

    def _load_config(self) -> None:
        path = _config_path()
        if not path.exists():
            self._config = TargetFileWatchConfig()
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            self._config = normalize_config(raw)
        except Exception as exc:
            self.logger.error("target file config load failed; feature stays disabled: %s", type(exc).__name__)
            self._config = TargetFileWatchConfig()

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

    def save_config(self, value: Any) -> dict[str, Any]:
        next_config = normalize_config(value)
        previous = self._config
        source_changed = _stable_url(previous.source_url) != _stable_url(next_config.source_url)
        newly_enabled = next_config.enabled and not previous.enabled
        needs_fresh_baseline = source_changed or newly_enabled
        if needs_fresh_baseline and not self.state_healthy:
            raise TargetFileWatchError("target_file_watch_state_unavailable")

        _atomic_json_write(_config_path(), asdict(next_config))
        self._config = next_config
        if needs_fresh_baseline:
            self._state = self._empty_state()
            self._state["source_url"] = next_config.source_url
            self._save_state()
        return self.status()

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
        return await check_directory_once(self, self.directory_resolver)

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


def create_target_file_watch_service() -> SafeTargetFileWatchService:
    """Create the watcher explicitly from application startup code.

    Keeping construction behind a factory prevents importing this module from
    reading runtime config/state files or creating background-task state.
    """
    return SafeTargetFileWatchService()
