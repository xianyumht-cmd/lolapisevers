from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "upstream_snapshots"
SNAPSHOT_SCHEMA_VERSION = 1
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_RESERVED_METADATA_KEYS = {
    "schema_version",
    "source_id",
    "captured_at",
    "content_sha256",
    "payload",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: Optional[datetime] = None) -> str:
    current = value or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class SnapshotLoadResult:
    ok: bool
    status: str
    source_id: str
    payload: Any = None
    captured_at: str = ""
    age_seconds: int = 0
    content_sha256: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    path: str = ""
    quarantined_path: str = ""


class PersistentSnapshotStore:
    """Atomic, validated, persistent snapshots for external upstream data.

    Each source is stored as one JSON envelope. Writes use a same-directory
    temporary file, ``flush``/``fsync``, and ``os.replace`` so a failed refresh
    never removes the previous valid snapshot.
    """

    def __init__(self, root: Optional[Path] = None, *, schema_version: int = SNAPSHOT_SCHEMA_VERSION):
        configured_root = str(os.getenv("UPSTREAM_SNAPSHOT_DIR") or "").strip()
        self.root = Path(root or configured_root or DEFAULT_SNAPSHOT_ROOT).expanduser().resolve()
        self.schema_version = int(schema_version)
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        self._locks_guard = threading.Lock()
        self._locks: Dict[str, threading.RLock] = {}

    @staticmethod
    def validate_source_id(source_id: str) -> str:
        normalized = str(source_id or "").strip()
        if not _SOURCE_ID_RE.fullmatch(normalized):
            raise ValueError("source_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        return normalized

    def _lock_for(self, source_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(source_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[source_id] = lock
            return lock

    def path_for(self, source_id: str) -> Path:
        normalized = self.validate_source_id(source_id)
        return self.root / f"{normalized}.json"

    def status_path_for(self, source_id: str) -> Path:
        normalized = self.validate_source_id(source_id)
        return self.root / f"{normalized}.status.json"

    @staticmethod
    def _atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    value,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def save(
        self,
        source_id: str,
        payload: Any,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        captured_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        normalized = self.validate_source_id(source_id)
        # Validate JSON serialization before touching the existing file.
        digest = _payload_sha256(payload)
        clean_metadata: Dict[str, Any] = {}
        for key, value in dict(metadata or {}).items():
            text_key = str(key)
            if text_key not in _RESERVED_METADATA_KEYS:
                clean_metadata[text_key] = value
        _canonical_json_bytes(clean_metadata)

        envelope: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "source_id": normalized,
            "captured_at": _utc_text(captured_at),
            "content_sha256": digest,
            "payload": payload,
            "metadata": clean_metadata,
        }
        path = self.path_for(normalized)
        with self._lock_for(normalized):
            self._atomic_write_json(path, envelope)
            # A successful refresh clears only the sidecar error state. The
            # snapshot envelope remains immutable evidence of the capture.
            status_path = self.status_path_for(normalized)
            if status_path.exists():
                self._atomic_write_json(
                    status_path,
                    {
                        "schema_version": self.schema_version,
                        "source_id": normalized,
                        "last_refresh_error_class": "",
                        "last_refresh_error_message": "",
                        "last_refresh_error_at": "",
                        "last_success_at": envelope["captured_at"],
                    },
                )
        return {
            "ok": True,
            "status": "saved",
            "source_id": normalized,
            "captured_at": envelope["captured_at"],
            "content_sha256": digest,
            "path": str(path),
        }

    def _quarantine_locked(self, path: Path) -> str:
        if not path.exists():
            return ""
        timestamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        quarantine = path.with_name(f"{path.stem}.bad.{timestamp}{path.suffix}")
        try:
            os.replace(path, quarantine)
            return str(quarantine)
        except OSError:
            return ""

    def load(self, source_id: str, max_age_seconds: Optional[int] = None) -> SnapshotLoadResult:
        normalized = self.validate_source_id(source_id)
        path = self.path_for(normalized)
        with self._lock_for(normalized):
            if not path.is_file():
                return SnapshotLoadResult(
                    ok=False,
                    status="missing",
                    source_id=normalized,
                    path=str(path),
                )
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("snapshot envelope is not an object")
                if raw.get("schema_version") != self.schema_version:
                    return SnapshotLoadResult(
                        ok=False,
                        status="incompatible",
                        source_id=normalized,
                        error="snapshot schema version mismatch",
                        path=str(path),
                    )
                if str(raw.get("source_id") or "") != normalized:
                    raise ValueError("snapshot source_id mismatch")
                captured_at = str(raw.get("captured_at") or "")
                captured_dt = _parse_utc(captured_at)
                payload = raw.get("payload")
                expected_digest = str(raw.get("content_sha256") or "")
                actual_digest = _payload_sha256(payload)
                if not expected_digest or expected_digest != actual_digest:
                    raise ValueError("snapshot payload hash mismatch")
                metadata = raw.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                age_seconds = max(0, int((_utc_now() - captured_dt).total_seconds()))
                if max_age_seconds is not None and age_seconds > max(0, int(max_age_seconds)):
                    return SnapshotLoadResult(
                        ok=False,
                        status="expired",
                        source_id=normalized,
                        captured_at=captured_at,
                        age_seconds=age_seconds,
                        content_sha256=actual_digest,
                        metadata=dict(metadata),
                        error="snapshot exceeded max_age_seconds",
                        path=str(path),
                    )
                return SnapshotLoadResult(
                    ok=True,
                    status="hit",
                    source_id=normalized,
                    payload=payload,
                    captured_at=captured_at,
                    age_seconds=age_seconds,
                    content_sha256=actual_digest,
                    metadata=dict(metadata),
                    path=str(path),
                )
            except Exception as exc:
                quarantined = self._quarantine_locked(path)
                return SnapshotLoadResult(
                    ok=False,
                    status="corrupt",
                    source_id=normalized,
                    error=str(exc),
                    path=str(path),
                    quarantined_path=quarantined,
                )

    def record_refresh_error(self, source_id: str, error_class: str, message: str = "") -> Dict[str, Any]:
        normalized = self.validate_source_id(source_id)
        error_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(error_class or "unknown").strip())[:96] or "unknown"
        safe_message = str(message or "").replace("\r", " ").replace("\n", " ").strip()[:500]
        status_path = self.status_path_for(normalized)
        with self._lock_for(normalized):
            previous: Dict[str, Any] = {}
            if status_path.is_file():
                try:
                    loaded = json.loads(status_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        previous = loaded
                except Exception:
                    previous = {}
            value = {
                "schema_version": self.schema_version,
                "source_id": normalized,
                "last_refresh_error_class": error_name,
                "last_refresh_error_message": safe_message,
                "last_refresh_error_at": _utc_text(),
                "last_success_at": str(previous.get("last_success_at") or ""),
            }
            self._atomic_write_json(status_path, value)
        return {"ok": True, "status": "recorded", **value, "path": str(status_path)}

    def status(self, source_id: str, max_age_seconds: Optional[int] = None) -> Dict[str, Any]:
        normalized = self.validate_source_id(source_id)
        loaded = self.load(normalized, max_age_seconds=max_age_seconds)
        status_path = self.status_path_for(normalized)
        refresh_status: Dict[str, Any] = {}
        with self._lock_for(normalized):
            if status_path.is_file():
                try:
                    value = json.loads(status_path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        refresh_status = value
                except Exception:
                    refresh_status = {"status_file_error": "invalid_json"}
        return {
            "source_id": normalized,
            "snapshot_status": loaded.status,
            "snapshot_ok": loaded.ok,
            "captured_at": loaded.captured_at,
            "age_seconds": loaded.age_seconds,
            "content_sha256": loaded.content_sha256,
            "path": loaded.path,
            "quarantined_path": loaded.quarantined_path,
            "error": loaded.error,
            "last_refresh_error_class": str(refresh_status.get("last_refresh_error_class") or ""),
            "last_refresh_error_message": str(refresh_status.get("last_refresh_error_message") or ""),
            "last_refresh_error_at": str(refresh_status.get("last_refresh_error_at") or ""),
            "last_success_at": str(refresh_status.get("last_success_at") or loaded.captured_at or ""),
        }
