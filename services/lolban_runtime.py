from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Callable, Mapping

from services.lolban_service import LolBanService, create_lolban_service


_MISSING = object()


def _service_from_environment() -> LolBanService:
    return create_lolban_service(strict_configuration=True)


def _initial_service_from_environment() -> LolBanService:
    return create_lolban_service(strict_configuration=False)


class LolBanRuntime:
    """Own the active LOL ban service and replace it atomically on reload."""

    def __init__(
        self,
        initial_service: LolBanService | None = None,
        *,
        service_factory: Callable[[], LolBanService] = _service_from_environment,
        initial_service_factory: Callable[[], LolBanService] = _initial_service_from_environment,
    ) -> None:
        self._lock = threading.RLock()
        self._service_factory = service_factory
        self._initial_service_factory = initial_service_factory
        self._service = initial_service
        self._loaded_at = (
            datetime.now(timezone.utc).isoformat()
            if initial_service is not None
            else ""
        )

    def _ensure_service_locked(self) -> LolBanService:
        if self._service is None:
            self._service = self._initial_service_factory()
            self._loaded_at = datetime.now(timezone.utc).isoformat()
        return self._service

    def service(self) -> LolBanService:
        with self._lock:
            return self._ensure_service_locked()

    def loaded_at(self) -> str:
        with self._lock:
            self._ensure_service_locked()
            return self._loaded_at

    def reload(self, environment: Mapping[str, str] | None = None) -> LolBanService:
        updates = {str(key): str(value) for key, value in dict(environment or {}).items()}
        with self._lock:
            previous = {key: os.environ.get(key, _MISSING) for key in updates}
            try:
                os.environ.update(updates)
                candidate = self._service_factory()
            except BaseException:
                for key, value in previous.items():
                    if value is _MISSING:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = str(value)
                raise

            self._service = candidate
            self._loaded_at = datetime.now(timezone.utc).isoformat()
            return candidate


_runtime = LolBanRuntime()


def get_lolban_service() -> LolBanService:
    return _runtime.service()


def get_lolban_loaded_at() -> str:
    return _runtime.loaded_at()


def reload_lolban_service(environment: Mapping[str, str] | None = None) -> LolBanService:
    return _runtime.reload(environment)
