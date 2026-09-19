from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .monitor_errors import safe_class_name, safe_code, sanitize_persisted_errors
from .providers import ShareSnapshot, snapshot_from_state, utc_now_iso


STATE_SCHEMA_VERSION = 6


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self._needs_migration = False
        self.data: dict[str, Any] = self._load()
        if self._needs_migration:
            self.save()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "version": STATE_SCHEMA_VERSION,
            "snapshots": {},
            "events": [],
            "last_scan": {},
            "pending_deliveries": {},
            "orphaned_watchers": {},
            "guard_candidates": {},
            "content_risk": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        with self.path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return self._empty_state()
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
            "content_risk": dict,
        }
        for key, expected_type in expected_containers.items():
            if not isinstance(data.get(key), expected_type):
                data[key] = expected_type()
                self._needs_migration = True
        self._needs_migration = sanitize_persisted_errors(data) or self._needs_migration
        return data

    def save(self) -> None:
        with self.lock:
            sanitize_persisted_errors(self.data)
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
                "error_code": safe_code(failure.get("error_code"), "scan_failed"),
                "error_class": safe_class_name(failure.get("error_class"), "MonitorError"),
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
                "error_code": safe_code(error_code, "snapshot_confirmation_pending"),
                "error_class": "SnapshotGuardPending",
                "retryable": True,
            }
            self.save()

    def append_event(self, event: dict[str, Any], max_events: int = 200) -> None:
        with self.lock:
            events = self.data.setdefault("events", [])
            event_id = str(event.get("id") or "")
            if event_id:
                events[:] = [
                    item
                    for item in events
                    if str(item.get("id") or "") != event_id
                ]
            events.insert(0, json.loads(json.dumps(event, ensure_ascii=False)))
            del events[max_events:]
            self.save()

    def pending_delivery_for(self, event_id: str) -> dict[str, Any] | None:
        with self.lock:
            raw = self.data.setdefault("pending_deliveries", {}).get(event_id)
            return (
                json.loads(json.dumps(raw, ensure_ascii=False))
                if isinstance(raw, dict)
                else None
            )

    def set_pending_delivery(self, event_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("pending_deliveries", {})[event_id] = value
            self.save()

    def clear_pending_delivery(self, event_id: str) -> None:
        with self.lock:
            self.data.setdefault("pending_deliveries", {}).pop(event_id, None)
            self.save()

    def content_risk_for(self, watcher_id: str) -> dict[str, Any] | None:
        with self.lock:
            raw = self.data.setdefault("content_risk", {}).get(watcher_id)
            return (
                json.loads(json.dumps(raw, ensure_ascii=False))
                if isinstance(raw, dict)
                else None
            )

    def set_content_risk(self, watcher_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("content_risk", {})[watcher_id] = json.loads(
                json.dumps(value, ensure_ascii=False)
            )
            self.save()

    def mark_event_superseded(
        self,
        event_id: str,
        *,
        active_event_id: str = "",
        reason: str = "source_advanced",
    ) -> bool:
        with self.lock:
            for event in self.data.setdefault("events", []):
                if (
                    not isinstance(event, dict)
                    or str(event.get("id") or event.get("event_id") or "") != event_id
                ):
                    continue
                event["delivery_state"] = "superseded"
                event["superseded_at"] = utc_now_iso()
                event["superseded_reason"] = safe_code(reason, "source_advanced")
                if active_event_id:
                    event["superseded_by_event_id"] = active_event_id
                self.save()
                return True
            return False

    def guard_candidate_for(self, watcher_id: str) -> dict[str, Any] | None:
        with self.lock:
            raw = self.data.setdefault("guard_candidates", {}).get(watcher_id)
            return (
                json.loads(json.dumps(raw, ensure_ascii=False))
                if isinstance(raw, dict)
                else None
            )

    def set_guard_candidate(self, watcher_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("guard_candidates", {})[watcher_id] = value
            self.save()

    def clear_guard_candidate(self, watcher_id: str) -> bool:
        with self.lock:
            removed = (
                self.data.setdefault("guard_candidates", {}).pop(watcher_id, None)
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
                if isinstance(value, dict)
                and str(value.get("watcher_id") or "") == watcher_id
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
            safe_reason = safe_code(reason, "source_advanced")
            events = self.data.setdefault("events", [])
            for event_id in superseded_ids:
                pending.pop(event_id, None)
                for event in events:
                    if (
                        not isinstance(event, dict)
                        or str(event.get("id") or event.get("event_id") or "")
                        != event_id
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
            content_risk = self.data.setdefault("content_risk", {})
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
                archived_risk = archived.get("content_risk")
                if watcher_id not in content_risk and isinstance(archived_risk, dict):
                    content_risk[watcher_id] = archived_risk
                changed = True

            tracked_ids = set(snapshots) | set(last_scan) | set(guards) | set(content_risk)
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
                archived_pending = (
                    dict(archived_pending)
                    if isinstance(archived_pending, dict)
                    else {}
                )
                for event_id, value in list(pending.items()):
                    if (
                        not isinstance(value, dict)
                        or str(value.get("watcher_id") or "") != watcher_id
                    ):
                        continue
                    archived_pending[event_id] = pending.pop(event_id)
                    moved = True
                if archived_pending:
                    record["pending_deliveries"] = archived_pending
                guard = guards.pop(watcher_id, None)
                if isinstance(guard, dict):
                    record["guard_candidate"] = guard
                    moved = True
                risk = content_risk.pop(watcher_id, None)
                if isinstance(risk, dict):
                    record["content_risk"] = risk
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
