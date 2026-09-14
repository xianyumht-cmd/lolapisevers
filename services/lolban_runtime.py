from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Callable, Mapping

from services.lolban_service import LolBanService, _create_default_service


_MISSING = object()


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _service_from_environment() -> LolBanService:
    return LolBanService(
        normal_cache_seconds=_env_int("LOL_BAN_NORMAL_CACHE_SECONDS", 60, minimum=1),
        banned_cache_seconds=_env_int("LOL_BAN_BANNED_CACHE_SECONDS", 300, minimum=1),
        stale_cache_seconds=_env_int("LOL_BAN_STALE_CACHE_SECONDS", 86400, minimum=0),
        max_stale_entries=_env_int("LOL_BAN_MAX_STALE_ENTRIES", 1024, minimum=1),
    )


class LolBanRuntime:
    """Own the active LOL ban service and replace it atomically on reload."""

    def __init__(
        self,
        initial_service: LolBanService | None = None,
        *,
        service_factory: Callable[[], LolBanService] = _service_from_environment,
    ) -> None:
        self._lock = threading.RLock()
        self._service_factory = service_factory
        self._service = initial_service or _create_default_service()
        self._loaded_at = datetime.now(timezone.utc).isoformat()

    def service(self) -> LolBanService:
        with self._lock:
            return self._service

    def loaded_at(self) -> str:
        with self._lock:
            return self._loaded_at

    def reload(self, environment: Mapping[str, str] | None = None) -> LolBanService:
        updates = {str(key): str(value) for key, value in dict(environment or {}).items()}
        with self._lock:
            previous = {key: os.environ.get(key, _MISSING) for key in updates}
            try:
                os.environ.update(updates)
                candidate = self._service_factory()
            except Exception:
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
