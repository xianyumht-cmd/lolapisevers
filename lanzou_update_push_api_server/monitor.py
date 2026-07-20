from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

from .config import AppConfig, WatcherConfig
from .providers import FileEntry, ProviderChain, ShareSnapshot, snapshot_from_state, utc_now_iso


def compare_snapshots(previous: ShareSnapshot, current: ShareSnapshot) -> dict[str, list[dict[str, Any]]]:
    previous_map = {item.id: item for item in previous.files}
    current_map = {item.id: item for item in current.files}
    added = [asdict(current_map[key]) for key in sorted(set(current_map) - set(previous_map))]
    removed = [asdict(previous_map[key]) for key in sorted(set(previous_map) - set(current_map))]
    changed: list[dict[str, Any]] = []
    for key in sorted(set(previous_map) & set(current_map)):
        old = previous_map[key]
        new = current_map[key]
        if old.fingerprint_payload() != new.fingerprint_payload():
            changed.append({"before": asdict(old), "after": asdict(new)})
    return {"added": added, "removed": removed, "changed": changed}


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "snapshots": {}, "events": [], "last_scan": {}}
        with self.path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"version": 1, "snapshots": {}, "events": [], "last_scan": {}}
        data.setdefault("version", 1)
        data.setdefault("snapshots", {})
        data.setdefault("events", [])
        data.setdefault("last_scan", {})
        return data

    def save(self) -> None:
        with self.lock:
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
    ) -> None:
        with self.lock:
            if commit_snapshot:
                self.data.setdefault("snapshots", {})[snapshot.watcher_id] = snapshot.to_dict()
            self.data.setdefault("last_scan", {})[snapshot.watcher_id] = {
                "ok": True,
                "at": utc_now_iso(),
                "provider": snapshot.provider,
                "file_count": len(snapshot.files),
                "snapshot_committed": commit_snapshot,
                "notification_pending": notification_pending,
            }
            self.save()

    def set_scan_error(self, watcher_id: str, error: str) -> None:
        with self.lock:
            self.data.setdefault("last_scan", {})[watcher_id] = {
                "ok": False,
                "at": utc_now_iso(),
                "error": error,
            }
            self.save()

    def append_event(self, event: dict[str, Any], max_events: int = 200) -> None:
        with self.lock:
            events = self.data.setdefault("events", [])
            events.insert(0, event)
            del events[max_events:]
            self.save()

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.data.get("events", []))[: max(1, min(200, limit))]


class LanzouMonitorService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = StateStore(config.state_path)
        self.provider_chain = ProviderChain(config)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._watcher_locks: dict[str, threading.Lock] = {}
        self._watcher_locks_guard = threading.Lock()

    def watcher_map(self) -> dict[str, WatcherConfig]:
        return {watcher.id: watcher for watcher in self.config.watchers}

    def reload_config(self, config: AppConfig) -> None:
        self.config = config
        self.provider_chain = ProviderChain(config)
        if self.store.path != config.state_path:
            self.store = StateStore(config.state_path)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "running": self._task is not None and not self._task.done(),
            "scan_interval_seconds": self.config.scan_interval_seconds,
            "watcher_count": len(self.config.watchers),
            "enabled_watcher_count": len([watcher for watcher in self.config.watchers if watcher.enabled]),
            "notify_target_count": len(self.config.notify_targets),
            "state_path": str(self.config.state_path),
            "last_scan": self.store.data.get("last_scan", {}),
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

    def _scan_watcher_unlocked_sync(self, watcher: WatcherConfig, notify: bool) -> dict[str, Any]:
        started = time.time()
        try:
            current = self.provider_chain.fetch(watcher)
            previous = self.store.snapshot_for(watcher.id)
            if previous is None:
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
            diff = compare_snapshots(previous, current)
            changed = bool(diff["added"] or diff["removed"] or diff["changed"])
            event = self._build_event(watcher, current, previous, diff) if changed else None
            snapshot_committed = not changed
            notification_pending = False
            if event and notify:
                event["notify_results"] = self._notify_targets(event)
                self.store.append_event(event)
                snapshot_committed = all(result.get("ok") is True for result in event["notify_results"])
                notification_pending = not snapshot_committed
            elif event:
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
            message = str(exc)
            self.store.set_scan_error(watcher.id, message)
            return {
                "ok": False,
                "watcher_id": watcher.id,
                "error": message,
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
            return f"hello，{values['title']}网盘检测到更新"

    def _build_event(
        self,
        watcher: WatcherConfig,
        current: ShareSnapshot,
        previous: ShareSnapshot,
        diff: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "type": "lanzou_update",
            "created_at": utc_now_iso(),
            "watcher_id": watcher.id,
            "title": current.title or watcher.title,
            "name": current.title or watcher.title,
            "url": watcher.url,
            "message": self._render_message(watcher, current),
            "provider": current.provider,
            "previous_signature": previous.signature,
            "current_signature": current.signature,
            "previous_file_count": len(previous.files),
            "current_file_count": len(current.files),
            "diff": diff,
            "files": [file.__dict__ for file in current.files],
        }

    def _notify_targets(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for target in self.config.notify_targets:
            if not target.enabled:
                continue
            started = time.time()
            try:
                response = requests.post(
                    target.url,
                    json=event,
                    headers={"content-type": "application/json", **target.headers},
                    timeout=target.timeout_seconds,
                )
                results.append(
                    {
                        "target": target.name,
                        "ok": 200 <= response.status_code < 300,
                        "status_code": response.status_code,
                        "elapsed_ms": int((time.time() - started) * 1000),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "target": target.name,
                        "ok": False,
                        "error": str(exc),
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
        event["notify_results"] = await asyncio.to_thread(self._notify_targets, event)
        self.store.append_event(event)
        return {"ok": True, "event": event}
