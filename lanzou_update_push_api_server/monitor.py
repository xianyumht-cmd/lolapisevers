from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

from .config import AppConfig, WatcherConfig
from .providers import (
    FileEntry,
    ProviderChain,
    ShareSnapshot,
    canonical_file_key,
    snapshot_from_state,
    utc_now_iso,
)

STATE_SCHEMA_VERSION = 5
_SAFE_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_ERROR_CONTEXT_KEYS = {
    "body",
    "exception",
    "exception_message",
    "headers",
    "message",
    "query",
    "request_body",
    "request_headers",
    "request_query",
    "request_url",
    "response_body",
    "response_headers",
    "response_url",
    "url",
}


def _safe_code(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_CODE_PATTERN.fullmatch(candidate) else fallback


def _safe_class_name(value: Any, fallback: str) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return candidate[:64] or fallback


def _safe_failure(exc: Exception, fallback_code: str) -> dict[str, Any]:
    status_code = None
    configured_code = getattr(exc, "error_code", "")
    configured_retryable = getattr(exc, "retryable", None)
    configured_status_code = getattr(exc, "status_code", None)
    if isinstance(configured_status_code, int):
        status_code = configured_status_code
    if configured_code:
        error_code = _safe_code(configured_code, fallback_code)
    elif isinstance(exc, requests.ConnectTimeout):
        error_code = "connect_timeout"
    elif isinstance(exc, requests.ReadTimeout):
        error_code = "read_timeout"
    elif isinstance(exc, requests.Timeout):
        error_code = "timeout"
    elif isinstance(exc, requests.ConnectionError):
        error_code = "connection_error"
    elif isinstance(exc, requests.HTTPError):
        error_code = "http_status"
        response = getattr(exc, "response", None)
        candidate = getattr(response, "status_code", None)
        status_code = int(candidate) if isinstance(candidate, int) else None
    elif isinstance(exc, (json.JSONDecodeError, ValueError)):
        error_code = "invalid_response"
    else:
        error_code = fallback_code

    if configured_retryable is None:
        retryable = not isinstance(exc, (json.JSONDecodeError, ValueError))
        if status_code is not None:
            retryable = status_code == 429 or status_code >= 500
    else:
        retryable = bool(configured_retryable)
    result: dict[str, Any] = {
        "error_code": error_code,
        "error_class": _safe_class_name(type(exc).__name__, "MonitorError"),
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _sanitize_persisted_errors(value: Any) -> bool:
    """Remove legacy free-form exception data from persisted monitor state."""
    changed = False
    if isinstance(value, list):
        for item in value:
            changed = _sanitize_persisted_errors(item) or changed
        return changed
    if not isinstance(value, dict):
        return False

    is_error_record = value.get("ok") is False or any(
        key in value
        for key in ("error", "error_code", "error_class", "exception")
    )
    if "error" in value:
        value.pop("error", None)
        value.setdefault("error_code", "legacy_error_redacted")
        value.setdefault("error_class", "LegacyPersistedError")
        value.setdefault("retryable", True)
        changed = True
        is_error_record = True
    if is_error_record:
        for key in list(value):
            if str(key).strip().lower() in _ERROR_CONTEXT_KEYS:
                value.pop(key, None)
                changed = True
    for item in list(value.values()):
        changed = _sanitize_persisted_errors(item) or changed
    return changed


def compare_snapshots(previous: ShareSnapshot, current: ShareSnapshot) -> dict[str, list[dict[str, Any]]]:
    use_provider_fingerprint = previous.provider == current.provider

    def fingerprint(item: FileEntry) -> dict[str, str]:
        return (
            item.fingerprint_payload()
            if use_provider_fingerprint
            else item.canonical_fingerprint_payload()
        )

    def grouped(files: list[FileEntry]) -> dict[str, list[FileEntry]]:
        result: dict[str, list[FileEntry]] = {}
        for item in files:
            result.setdefault(canonical_file_key(item), []).append(item)
        for values in result.values():
            values.sort(
                key=lambda item: json.dumps(
                    fingerprint(item),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return result

    previous_map = grouped(previous.files)
    current_map = grouped(current.files)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for key in sorted(set(previous_map) | set(current_map)):
        old_items = previous_map.get(key, [])
        new_items = current_map.get(key, [])
        paired_count = min(len(old_items), len(new_items))
        for index in range(paired_count):
            old = old_items[index]
            new = new_items[index]
            if fingerprint(old) != fingerprint(new):
                changed.append({"before": asdict(old), "after": asdict(new)})
        removed.extend(asdict(item) for item in old_items[paired_count:])
        added.extend(asdict(item) for item in new_items[paired_count:])
    return {"added": added, "removed": removed, "changed": changed}


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self._needs_migration = False
        self.data: dict[str, Any] = self._load()
        if self._needs_migration:
            self.save()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": STATE_SCHEMA_VERSION,
                "snapshots": {},
                "events": [],
                "last_scan": {},
                "pending_deliveries": {},
                "orphaned_watchers": {},
                "guard_candidates": {},
            }
        with self.path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {
                "version": STATE_SCHEMA_VERSION,
                "snapshots": {},
                "events": [],
                "last_scan": {},
                "pending_deliveries": {},
                "orphaned_watchers": {},
                "guard_candidates": {},
            }
        try:
            loaded_version = int(data.get("version") or 1)
        except (TypeError, ValueError):
            loaded_version = 1
            self._needs_migration = True
        self._needs_migration = (
            self._needs_migration
            or loaded_version < STATE_SCHEMA_VERSION
            or "orphaned_watchers" not in data
        )
        data["version"] = max(loaded_version, STATE_SCHEMA_VERSION)
        expected_containers = {
            "snapshots": dict,
            "events": list,
            "last_scan": dict,
            "pending_deliveries": dict,
            "orphaned_watchers": dict,
            "guard_candidates": dict,
        }
        for key, expected_type in expected_containers.items():
            if not isinstance(data.get(key), expected_type):
                data[key] = expected_type()
                self._needs_migration = True
        self._needs_migration = _sanitize_persisted_errors(data) or self._needs_migration
        return data

    def save(self) -> None:
        with self.lock:
            _sanitize_persisted_errors(self.data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temp_path.replace(self.path)

    def snapshot_for(self, watcher_id: str) -> ShareSnapshot | None:
        with self.lock:
            raw = self.data.get("snapshots", {}).get(watcher_id)
            if not isinstance(raw, dict):
                return None
            return snapshot_from_state(raw)

    def set_snapshot(self, snapshot: ShareSnapshot) -> None:
        self.record_scan_success(snapshot, commit_snapshot=True)

    def record_scan_success(
        self,
        snapshot: ShareSnapshot,
        *,
        commit_snapshot: bool,
        notification_pending: bool = False,
        rebaseline_reason: str = "",
    ) -> None:
        with self.lock:
            if commit_snapshot:
                self.data.setdefault("snapshots", {})[snapshot.watcher_id] = snapshot.to_dict()
            scan_record = {
                "ok": True,
                "at": utc_now_iso(),
                "provider": snapshot.provider,
                "file_count": len(snapshot.files),
                "snapshot_committed": commit_snapshot,
                "notification_pending": notification_pending,
            }
            if rebaseline_reason:
                scan_record["rebaseline"] = True
                scan_record["rebaseline_reason"] = rebaseline_reason
            self.data.setdefault("last_scan", {})[snapshot.watcher_id] = scan_record
            self.save()

    def set_scan_error(self, watcher_id: str, failure: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("last_scan", {})[watcher_id] = {
                "ok": False,
                "at": utc_now_iso(),
                "error_code": _safe_code(
                    failure.get("error_code"),
                    "scan_failed",
                ),
                "error_class": _safe_class_name(
                    failure.get("error_class"),
                    "MonitorError",
                ),
                "retryable": failure.get("retryable") is True,
            }
            status_code = failure.get("status_code")
            if isinstance(status_code, int):
                self.data["last_scan"][watcher_id]["status_code"] = status_code
            self.save()

    def record_guarded_scan(
        self,
        snapshot: ShareSnapshot,
        *,
        error_code: str,
        seen_count: int,
    ) -> None:
        with self.lock:
            self.data.setdefault("last_scan", {})[snapshot.watcher_id] = {
                "ok": False,
                "at": utc_now_iso(),
                "provider": snapshot.provider,
                "file_count": len(snapshot.files),
                "snapshot_committed": False,
                "notification_pending": False,
                "guard_pending": True,
                "guard_seen_count": max(1, int(seen_count)),
                "error_code": _safe_code(
                    error_code,
                    "snapshot_confirmation_pending",
                ),
                "error_class": "SnapshotGuardPending",
                "retryable": True,
            }
            self.save()

    def append_event(self, event: dict[str, Any], max_events: int = 200) -> None:
        with self.lock:
            events = self.data.setdefault("events", [])
            event_id = str(event.get("id") or "")
            if event_id:
                events[:] = [item for item in events if str(item.get("id") or "") != event_id]
            events.insert(
                0,
                json.loads(json.dumps(event, ensure_ascii=False)),
            )
            del events[max_events:]
            self.save()

    def pending_delivery_for(self, event_id: str) -> dict[str, Any] | None:
        with self.lock:
            raw = self.data.setdefault("pending_deliveries", {}).get(event_id)
            return json.loads(json.dumps(raw, ensure_ascii=False)) if isinstance(raw, dict) else None

    def set_pending_delivery(self, event_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("pending_deliveries", {})[event_id] = value
            self.save()

    def clear_pending_delivery(self, event_id: str) -> None:
        with self.lock:
            self.data.setdefault("pending_deliveries", {}).pop(event_id, None)
            self.save()

    def guard_candidate_for(self, watcher_id: str) -> dict[str, Any] | None:
        with self.lock:
            raw = self.data.setdefault("guard_candidates", {}).get(watcher_id)
            return (
                json.loads(json.dumps(raw, ensure_ascii=False))
                if isinstance(raw, dict)
                else None
            )

    def set_guard_candidate(
        self,
        watcher_id: str,
        value: dict[str, Any],
    ) -> None:
        with self.lock:
            self.data.setdefault("guard_candidates", {})[watcher_id] = value
            self.save()

    def clear_guard_candidate(self, watcher_id: str) -> bool:
        with self.lock:
            removed = (
                self.data.setdefault("guard_candidates", {}).pop(
                    watcher_id,
                    None,
                )
                is not None
            )
            if removed:
                self.save()
            return removed

    def clear_pending_for_watcher(self, watcher_id: str) -> int:
        with self.lock:
            pending = self.data.setdefault("pending_deliveries", {})
            event_ids = [
                event_id
                for event_id, value in pending.items()
                if isinstance(value, dict) and str(value.get("watcher_id") or "") == watcher_id
            ]
            for event_id in event_ids:
                pending.pop(event_id, None)
            if event_ids:
                self.save()
            return len(event_ids)

    def supersede_pending_for_watcher(
        self,
        watcher_id: str,
        *,
        active_event_id: str = "",
        reason: str = "source_advanced",
    ) -> int:
        """Keep at most one active delivery per watcher and retain audit history."""
        with self.lock:
            pending = self.data.setdefault("pending_deliveries", {})
            superseded_ids = [
                event_id
                for event_id, value in pending.items()
                if event_id != active_event_id
                and isinstance(value, dict)
                and str(value.get("watcher_id") or "") == watcher_id
            ]
            if not superseded_ids:
                return 0

            superseded_at = utc_now_iso()
            safe_reason = _safe_code(reason, "source_advanced")
            events = self.data.setdefault("events", [])
            for event_id in superseded_ids:
                pending.pop(event_id, None)
                for event in events:
                    if (
                        not isinstance(event, dict)
                        or str(event.get("id") or event.get("event_id") or "") != event_id
                    ):
                        continue
                    event["delivery_state"] = "superseded"
                    event["superseded_at"] = superseded_at
                    event["superseded_reason"] = safe_reason
                    if active_event_id:
                        event["superseded_by_event_id"] = active_event_id
                    break
            self.save()
            return len(superseded_ids)

    def reconcile_watchers(
        self,
        active_watcher_ids: set[str],
        watcher_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Archive removed watcher state and restore it when the ID returns."""
        with self.lock:
            snapshots = self.data.setdefault("snapshots", {})
            last_scan = self.data.setdefault("last_scan", {})
            pending = self.data.setdefault("pending_deliveries", {})
            orphans = self.data.setdefault("orphaned_watchers", {})
            guards = self.data.setdefault("guard_candidates", {})
            changed = False

            for watcher_id in sorted(active_watcher_ids):
                archived = orphans.pop(watcher_id, None)
                if not isinstance(archived, dict):
                    continue
                if watcher_id not in snapshots and isinstance(archived.get("snapshot"), dict):
                    snapshots[watcher_id] = archived["snapshot"]
                if watcher_id not in last_scan and isinstance(archived.get("last_scan"), dict):
                    last_scan[watcher_id] = archived["last_scan"]
                archived_pending = archived.get("pending_deliveries")
                if isinstance(archived_pending, dict):
                    for event_id, value in archived_pending.items():
                        if isinstance(value, dict):
                            pending.setdefault(event_id, value)
                archived_guard = archived.get("guard_candidate")
                if watcher_id not in guards and isinstance(archived_guard, dict):
                    guards[watcher_id] = archived_guard
                changed = True

            tracked_ids = set(snapshots) | set(last_scan) | set(guards)
            tracked_ids.update(
                str(value.get("watcher_id") or "")
                for value in pending.values()
                if isinstance(value, dict) and value.get("watcher_id")
            )
            for watcher_id in sorted(tracked_ids - active_watcher_ids):
                archived = orphans.get(watcher_id)
                record = dict(archived) if isinstance(archived, dict) else {}
                moved = False
                snapshot = snapshots.pop(watcher_id, None)
                if isinstance(snapshot, dict):
                    record["snapshot"] = snapshot
                    moved = True
                scan = last_scan.pop(watcher_id, None)
                if isinstance(scan, dict):
                    record["last_scan"] = scan
                    moved = True
                archived_pending = record.get("pending_deliveries")
                archived_pending = dict(archived_pending) if isinstance(archived_pending, dict) else {}
                for event_id, value in list(pending.items()):
                    if not isinstance(value, dict) or str(value.get("watcher_id") or "") != watcher_id:
                        continue
                    archived_pending[event_id] = pending.pop(event_id)
                    moved = True
                if archived_pending:
                    record["pending_deliveries"] = archived_pending
                guard = guards.pop(watcher_id, None)
                if isinstance(guard, dict):
                    record["guard_candidate"] = guard
                    moved = True
                metadata = (watcher_metadata or {}).get(watcher_id)
                if isinstance(metadata, dict):
                    record["watcher"] = metadata
                if moved:
                    record.setdefault("archived_at", utc_now_iso())
                    orphans[watcher_id] = record
                    changed = True

            if changed:
                self.save()

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(
                json.dumps(
                    list(self.data.get("events", []))[: max(1, min(200, limit))],
                    ensure_ascii=False,
                )
            )


class LanzouMonitorService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = StateStore(config.state_path)
        self.provider_chain = ProviderChain(config)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._watcher_locks: dict[str, threading.Lock] = {}
        self._watcher_locks_guard = threading.Lock()
        self.store.reconcile_watchers(
            set(self.watcher_map()),
            self._watcher_metadata(self.config.watchers),
        )

    def watcher_map(self) -> dict[str, WatcherConfig]:
        return {watcher.id: watcher for watcher in self.config.watchers}

    @staticmethod
    def _watcher_metadata(watchers: list[WatcherConfig]) -> dict[str, dict[str, Any]]:
        return {
            watcher.id: {
                "id": watcher.id,
                "title": watcher.title,
                "url": watcher.url,
                "enabled": watcher.enabled,
                "max_pages": watcher.max_pages,
            }
            for watcher in watchers
        }

    def reload_config(self, config: AppConfig) -> None:
        old_watchers = self.watcher_map()
        new_watcher_ids = {watcher.id for watcher in config.watchers}
        removed_ids = sorted(set(old_watchers) - new_watcher_ids)
        locks = [self._lock_for_watcher(watcher_id) for watcher_id in removed_ids]
        for lock in locks:
            lock.acquire()
        try:
            self.config = config
            self.provider_chain = ProviderChain(config)
            if self.store.path != config.state_path:
                self.store = StateStore(config.state_path)
            self.store.reconcile_watchers(
                new_watcher_ids,
                self._watcher_metadata(list(old_watchers.values())),
            )
        finally:
            for lock in reversed(locks):
                lock.release()

    def status(self) -> dict[str, Any]:
        enabled_ids = {watcher.id for watcher in self.config.watchers if watcher.enabled}
        with self.store.lock:
            last_scan = dict(self.store.data.get("last_scan", {}))
            pending_deliveries = dict(self.store.data.get("pending_deliveries", {}))
            orphan_count = len(self.store.data.get("orphaned_watchers", {}))
            guard_candidates = dict(self.store.data.get("guard_candidates", {}))
        failed_ids = {
            watcher_id
            for watcher_id in enabled_ids
            if isinstance(last_scan.get(watcher_id), dict)
            and last_scan[watcher_id].get("ok") is False
            and last_scan[watcher_id].get("guard_pending") is not True
        }
        pending_ids = {
            str(value.get("watcher_id") or "")
            for value in pending_deliveries.values()
            if isinstance(value, dict) and str(value.get("watcher_id") or "") in enabled_ids
        }
        pending_ids.update(
            watcher_id
            for watcher_id in enabled_ids
            if isinstance(last_scan.get(watcher_id), dict)
            and last_scan[watcher_id].get("notification_pending") is True
        )
        never_scanned_ids = enabled_ids - set(last_scan)
        guarded_ids = enabled_ids & set(guard_candidates)
        running = self._task is not None and not self._task.done()
        counts = {
            "enabled": len(enabled_ids),
            "failed": len(failed_ids),
            "pending": len(pending_ids),
            "never_scanned": len(never_scanned_ids),
            "orphan": orphan_count,
            "guarded": len(guarded_ids),
        }
        degraded_reasons = []
        if not running:
            degraded_reasons.append("background_loop_not_running")
        degraded_reasons.extend(
            name
            for name in ("failed", "pending", "never_scanned", "orphan", "guarded")
            if counts[name] > 0
        )
        ready = not degraded_reasons
        return {
            "ok": ready,
            "status": "ready" if ready else "degraded",
            "ready": ready,
            "degraded": not ready,
            "degraded_reasons": degraded_reasons,
            "running": running,
            "scan_interval_seconds": self.config.scan_interval_seconds,
            "watcher_count": len(self.config.watchers),
            "enabled_watcher_count": counts["enabled"],
            "failed_watcher_count": counts["failed"],
            "pending_watcher_count": counts["pending"],
            "never_scanned_watcher_count": counts["never_scanned"],
            "orphan_watcher_count": counts["orphan"],
            "guarded_watcher_count": counts["guarded"],
            "watchers": counts,
            "notify_target_count": len(self.config.notify_targets),
            "state_path": str(self.config.state_path),
            "last_scan": last_scan,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task

    async def _run_loop(self) -> None:
        first = True
        while not self._stop_event.is_set():
            if first and not self.config.scan_on_start:
                first = False
            else:
                await self.scan_all(notify=True, staggered=True)
                first = False
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.scan_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def scan_all(self, notify: bool = True, staggered: bool = False) -> list[dict[str, Any]]:
        enabled_watchers = [watcher for watcher in self.config.watchers if watcher.enabled]
        results = []
        batch_size = self.config.scan_batch_size if staggered else 0
        pause_seconds = self.config.scan_batch_pause_seconds if staggered else 0
        for index, watcher in enumerate(enabled_watchers):
            results.append(await self.scan_watcher(watcher.id, notify=notify))
            is_last = index >= len(enabled_watchers) - 1
            should_pause = batch_size > 0 and pause_seconds > 0 and (index + 1) % batch_size == 0
            if should_pause and not is_last:
                await asyncio.sleep(pause_seconds)
        return results

    async def scan_watcher(self, watcher_id: str, notify: bool = True) -> dict[str, Any]:
        watcher = self.watcher_map().get(watcher_id)
        if not watcher:
            return {"ok": False, "watcher_id": watcher_id, "error": "watcher_not_found"}
        if not watcher.enabled:
            return {"ok": False, "watcher_id": watcher_id, "error": "watcher_disabled"}
        return await asyncio.to_thread(self._scan_watcher_sync, watcher, notify)

    def _scan_watcher_sync(self, watcher: WatcherConfig, notify: bool) -> dict[str, Any]:
        with self._lock_for_watcher(watcher.id):
            return self._scan_watcher_unlocked_sync(watcher, notify)

    def _lock_for_watcher(self, watcher_id: str) -> threading.Lock:
        with self._watcher_locks_guard:
            return self._watcher_locks.setdefault(watcher_id, threading.Lock())

    def _confirm_guard_candidate(
        self,
        watcher: WatcherConfig,
        current: ShareSnapshot,
        *,
        kind: str,
    ) -> tuple[bool, int]:
        safe_kind = _safe_code(kind, "snapshot_guard")
        candidate_key = (
            f"{safe_kind}:{_safe_code(current.provider, 'provider')}:"
            f"{current.signature}"
        )
        existing = self.store.guard_candidate_for(watcher.id) or {}
        seen_count = (
            int(existing.get("seen_count") or 0) + 1
            if existing.get("candidate_key") == candidate_key
            else 1
        )
        now = utc_now_iso()
        self.store.set_guard_candidate(
            watcher.id,
            {
                "watcher_id": watcher.id,
                "kind": safe_kind,
                "candidate_key": candidate_key,
                "provider": _safe_code(current.provider, "provider"),
                "signature": current.signature,
                "seen_count": seen_count,
                "first_seen_at": (
                    existing.get("first_seen_at")
                    if existing.get("candidate_key") == candidate_key
                    else now
                ),
                "last_seen_at": now,
            },
        )
        return seen_count >= 2, seen_count

    def _scan_watcher_unlocked_sync(self, watcher: WatcherConfig, notify: bool) -> dict[str, Any]:
        started = time.time()
        try:
            current = self.provider_chain.fetch(watcher)
            previous = self.store.snapshot_for(watcher.id)
            empty_confirmed = False
            if not current.files and (previous is None or previous.files):
                empty_confirmed, seen_count = self._confirm_guard_candidate(
                    watcher,
                    current,
                    kind="empty_snapshot",
                )
                if not empty_confirmed:
                    self.store.record_guarded_scan(
                        current,
                        error_code="empty_snapshot_confirmation_pending",
                        seen_count=seen_count,
                    )
                    return {
                        "ok": False,
                        "watcher_id": watcher.id,
                        "title": current.title,
                        "guarded": True,
                        "guard_kind": "empty_snapshot",
                        "guard_seen_count": seen_count,
                        "error_code": "empty_snapshot_confirmation_pending",
                        "error_class": "SnapshotGuardPending",
                        "retryable": True,
                        "snapshot_committed": False,
                        "elapsed_ms": int((time.time() - started) * 1000),
                    }
            elif current.files:
                existing_guard = self.store.guard_candidate_for(watcher.id)
                if (
                    isinstance(existing_guard, dict)
                    and existing_guard.get("kind") == "empty_snapshot"
                ):
                    self.store.clear_guard_candidate(watcher.id)
            if previous is None:
                self.store.clear_guard_candidate(watcher.id)
                self.store.set_snapshot(current)
                return {
                    "ok": True,
                    "watcher_id": watcher.id,
                    "title": current.title,
                    "baseline": True,
                    "file_count": len(current.files),
                    "provider": current.provider,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
            previous_url = previous.url.strip().rstrip("/")
            current_url = current.url.strip().rstrip("/")
            rebaseline_reason = ""
            if previous_url != current_url:
                rebaseline_reason = "watcher_url_changed"
            elif previous.provider and current.provider != previous.provider and current.signature != previous.signature:
                if empty_confirmed:
                    rebaseline_reason = "provider_changed_with_confirmed_empty_snapshot"
                else:
                    provider_confirmed, seen_count = self._confirm_guard_candidate(
                        watcher,
                        current,
                        kind="provider_switch",
                    )
                    if not provider_confirmed:
                        self.store.record_guarded_scan(
                            current,
                            error_code="provider_switch_confirmation_pending",
                            seen_count=seen_count,
                        )
                        return {
                            "ok": False,
                            "watcher_id": watcher.id,
                            "title": current.title,
                            "guarded": True,
                            "guard_kind": "provider_switch",
                            "guard_seen_count": seen_count,
                            "error_code": "provider_switch_confirmation_pending",
                            "error_class": "SnapshotGuardPending",
                            "retryable": True,
                            "snapshot_committed": False,
                            "elapsed_ms": int((time.time() - started) * 1000),
                        }
                    rebaseline_reason = "provider_changed_with_non_equivalent_snapshot"
            if rebaseline_reason:
                self.store.clear_guard_candidate(watcher.id)
                discarded_pending = self.store.supersede_pending_for_watcher(
                    watcher.id,
                    reason="watcher_rebaselined",
                )
                self.store.record_scan_success(
                    current,
                    commit_snapshot=True,
                    rebaseline_reason=rebaseline_reason,
                )
                return {
                    "ok": True,
                    "watcher_id": watcher.id,
                    "title": current.title,
                    "baseline": False,
                    "rebaseline": True,
                    "rebaseline_reason": rebaseline_reason,
                    "notification_suppressed": True,
                    "discarded_pending_delivery_count": discarded_pending,
                    "file_count": len(current.files),
                    "provider": current.provider,
                    "snapshot_committed": True,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
            self.store.clear_guard_candidate(watcher.id)
            diff = compare_snapshots(previous, current)
            changed = bool(diff["added"] or diff["removed"] or diff["changed"])
            event = self._build_event(watcher, current, previous, diff) if changed else None
            if event:
                superseded_pending = self.store.supersede_pending_for_watcher(
                    watcher.id,
                    active_event_id=event["id"],
                    reason="source_advanced",
                )
                if superseded_pending:
                    event["superseded_pending_delivery_count"] = superseded_pending
            else:
                self.store.supersede_pending_for_watcher(
                    watcher.id,
                    reason="source_returned_to_baseline",
                )
            snapshot_committed = not changed
            notification_pending = False
            if event and notify:
                pending = self.store.pending_delivery_for(event["id"]) or {}
                previous_results = pending.get("target_results") if isinstance(pending.get("target_results"), dict) else {}
                enabled_target_names = [target.name for target in self.config.notify_targets if target.enabled]
                remaining_target_names = {
                    name
                    for name in enabled_target_names
                    if not isinstance(previous_results.get(name), dict)
                    or previous_results[name].get("ok") is not True
                }
                attempted_results = self._notify_targets(event, remaining_target_names)
                merged_results = dict(previous_results)
                for result in attempted_results:
                    merged_results[str(result.get("target") or "")] = result
                event["notify_results"] = [
                    merged_results[name]
                    for name in enabled_target_names
                    if isinstance(merged_results.get(name), dict)
                ]
                if not enabled_target_names:
                    delivery_state = "skipped"
                else:
                    successful = len([result for result in event["notify_results"] if result.get("ok") is True])
                    delivery_state = (
                        "complete"
                        if successful == len(enabled_target_names)
                        else "partial"
                        if successful > 0
                        else "failed"
                    )
                event["delivery_state"] = delivery_state
                self.store.append_event(event)
                snapshot_committed = delivery_state == "complete"
                notification_pending = not snapshot_committed
                if snapshot_committed:
                    self.store.clear_pending_delivery(event["id"])
                else:
                    self.store.set_pending_delivery(
                        event["id"],
                        {
                            "event_id": event["id"],
                            "watcher_id": watcher.id,
                            "previous_signature": previous.provider_signature,
                            "current_signature": current.provider_signature,
                            "previous_canonical_signature": previous.signature,
                            "current_canonical_signature": current.signature,
                            "created_at": pending.get("created_at") or event["created_at"],
                            "updated_at": utc_now_iso(),
                            "delivery_state": delivery_state,
                            "target_results": merged_results,
                        },
                    )
            elif event:
                event["delivery_state"] = "skipped"
                notification_pending = True
            self.store.record_scan_success(
                current,
                commit_snapshot=snapshot_committed,
                notification_pending=notification_pending,
            )
            return {
                "ok": True,
                "watcher_id": watcher.id,
                "title": current.title,
                "changed": changed,
                "file_count": len(current.files),
                "provider": current.provider,
                "diff": diff,
                "event": event,
                "snapshot_committed": snapshot_committed,
                "notification_pending": notification_pending,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:
            failure = _safe_failure(exc, "scan_failed")
            self.store.set_scan_error(watcher.id, failure)
            return {
                "ok": False,
                "watcher_id": watcher.id,
                **failure,
                "elapsed_ms": int((time.time() - started) * 1000),
            }

    def _render_message(self, watcher: WatcherConfig, snapshot: ShareSnapshot) -> str:
        values = {
            "title": snapshot.title or watcher.title,
            "name": snapshot.title or watcher.title,
            "watcher_id": watcher.id,
            "url": watcher.url,
        }
        try:
            return self.config.notification_template.format(**values)
        except Exception:
            return f"检测到网盘更新：{values['title']}\n{values['url']}"

    def _build_event(
        self,
        watcher: WatcherConfig,
        current: ShareSnapshot,
        previous: ShareSnapshot,
        diff: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    f"lanzou-update:{watcher.id}:"
                    f"{previous.provider_signature}:{current.provider_signature}"
                ),
            )
        )
        return {
            "id": event_id,
            "event_id": event_id,
            "type": "lanzou_update",
            "created_at": utc_now_iso(),
            "watcher_id": watcher.id,
            "title": current.title or watcher.title,
            "name": current.title or watcher.title,
            "url": watcher.url,
            "message": self._render_message(watcher, current),
            "provider": current.provider,
            "previous_signature": previous.provider_signature,
            "current_signature": current.provider_signature,
            "previous_canonical_signature": previous.signature,
            "current_canonical_signature": current.signature,
            "previous_file_count": len(previous.files),
            "current_file_count": len(current.files),
            "diff": diff,
            "files": [file.__dict__ for file in current.files],
        }

    def _notify_targets(
        self,
        event: dict[str, Any],
        target_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for target in self.config.notify_targets:
            if not target.enabled:
                continue
            if target_names is not None and target.name not in target_names:
                continue
            started = time.time()
            try:
                response = requests.post(
                    target.url,
                    json=event,
                    headers={"content-type": "application/json", **target.headers},
                    timeout=target.timeout_seconds,
                )
                try:
                    response_body = response.json()
                except ValueError:
                    response_body = {}
                raw_delivery_state = (
                    response_body.get("deliveryState")
                    or response_body.get("delivery_state")
                    or ""
                    if isinstance(response_body, dict)
                    else ""
                )
                candidate_delivery_state = (
                    str(raw_delivery_state).strip().lower()
                    if isinstance(raw_delivery_state, str)
                    else ""
                )
                delivery_state = (
                    candidate_delivery_state
                    if candidate_delivery_state
                    in {"complete", "partial", "failed", "skipped"}
                    else ""
                )
                http_ok = 200 <= response.status_code < 300
                acknowledged = (
                    http_ok
                    and isinstance(response_body, dict)
                    and response_body.get("ok") is True
                    and delivery_state == "complete"
                )
                result: dict[str, Any] = {
                    "target": target.name,
                    "ok": acknowledged,
                    "status_code": response.status_code,
                    "acknowledged": acknowledged,
                    "delivery_state": delivery_state,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
                if not acknowledged:
                    if not http_ok:
                        result.update(
                            {
                                "error_code": "callback_http_status",
                                "error_class": "CallbackHttpStatusError",
                                "retryable": response.status_code == 429
                                or response.status_code >= 500,
                            }
                        )
                    elif not isinstance(response_body, dict) or response_body.get("ok") is not True:
                        result.update(
                            {
                                "error_code": "callback_not_acknowledged",
                                "error_class": "CallbackAcknowledgementError",
                                "retryable": True,
                            }
                        )
                    else:
                        result.update(
                            {
                                "error_code": "callback_delivery_incomplete",
                                "error_class": "CallbackDeliveryIncomplete",
                                "retryable": True,
                            }
                        )
                results.append(result)
            except Exception as exc:
                results.append(
                    {
                        "target": target.name,
                        "ok": False,
                        **_safe_failure(exc, "callback_transport_error"),
                        "elapsed_ms": int((time.time() - started) * 1000),
                    }
                )
        return results

    async def send_test_event(self, watcher_id: str | None = None) -> dict[str, Any]:
        watcher = self.config.watchers[0] if self.config.watchers else None
        if watcher_id:
            watcher = self.watcher_map().get(watcher_id)
        if not watcher:
            return {"ok": False, "error": "watcher_not_found"}
        fake_file = FileEntry(id="test", name="test.txt")
        current = ShareSnapshot(
            watcher_id=watcher.id,
            title=watcher.title,
            url=watcher.url,
            provider="test",
            fetched_at=utc_now_iso(),
            files=[fake_file],
        )
        event = {
            "id": str(uuid.uuid4()),
            "event_id": "",
            "type": "lanzou_update_test",
            "created_at": utc_now_iso(),
            "watcher_id": watcher.id,
            "title": watcher.title,
            "name": watcher.title,
            "url": watcher.url,
            "message": self._render_message(watcher, current),
            "provider": "test",
            "diff": {"added": [asdict(fake_file)], "removed": [], "changed": []},
            "files": [asdict(fake_file)],
        }
        event["event_id"] = event["id"]
        event["notify_results"] = await asyncio.to_thread(self._notify_targets, event)
        enabled_target_count = len([target for target in self.config.notify_targets if target.enabled])
        successful = len([result for result in event["notify_results"] if result.get("ok") is True])
        event["delivery_state"] = (
            "complete"
            if enabled_target_count > 0 and successful == enabled_target_count
            else "partial"
            if successful > 0
            else "failed"
            if enabled_target_count > 0
            else "skipped"
        )
        self.store.append_event(event)
        return {
            "ok": event["delivery_state"] == "complete",
            "delivery_state": event["delivery_state"],
            "event": event,
        }
