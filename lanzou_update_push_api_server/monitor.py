from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

import requests

from .config import AppConfig, WatcherConfig
from .monitor_diff import compare_snapshots
from .monitor_errors import (
    safe_class_name as _safe_class_name,
    safe_code as _safe_code,
    safe_failure as _safe_failure,
    sanitize_persisted_errors as _sanitize_persisted_errors,
)
from .monitor_state import STATE_SCHEMA_VERSION, StateStore
from .providers import FileEntry, ProviderChain, ShareSnapshot, utc_now_iso


class LanzouMonitorService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = StateStore(config.state_path)
        self.provider_chain = ProviderChain(config)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._started_monotonic = 0.0
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
            if isinstance(value, dict)
            and str(value.get("watcher_id") or "") in enabled_ids
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
        warming_up = bool(
            running
            and not self.config.scan_on_start
            and never_scanned_ids
            and self._started_monotonic
            and time.monotonic() - self._started_monotonic
            < self.config.scan_interval_seconds
        )
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
            for name in ("failed", "pending", "orphan", "guarded")
            if counts[name] > 0
        )
        if counts["never_scanned"] > 0 and not warming_up:
            degraded_reasons.append("never_scanned")
        ready = not degraded_reasons
        return {
            "ok": ready,
            "status": "ready" if ready else "degraded",
            "ready": ready,
            "degraded": not ready,
            "degraded_reasons": degraded_reasons,
            "running": running,
            "warming_up": warming_up,
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
        self._started_monotonic = time.monotonic()
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
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.scan_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def scan_all(
        self,
        notify: bool = True,
        staggered: bool = False,
    ) -> list[dict[str, Any]]:
        enabled_watchers = [
            watcher for watcher in self.config.watchers if watcher.enabled
        ]
        results = []
        batch_size = self.config.scan_batch_size if staggered else 0
        pause_seconds = self.config.scan_batch_pause_seconds if staggered else 0
        for index, watcher in enumerate(enabled_watchers):
            results.append(await self.scan_watcher(watcher.id, notify=notify))
            is_last = index >= len(enabled_watchers) - 1
            should_pause = (
                batch_size > 0
                and pause_seconds > 0
                and (index + 1) % batch_size == 0
            )
            if should_pause and not is_last:
                await asyncio.sleep(pause_seconds)
        return results

    async def scan_watcher(
        self,
        watcher_id: str,
        notify: bool = True,
    ) -> dict[str, Any]:
        watcher = self.watcher_map().get(watcher_id)
        if not watcher:
            return {"ok": False, "watcher_id": watcher_id, "error": "watcher_not_found"}
        if not watcher.enabled:
            return {"ok": False, "watcher_id": watcher_id, "error": "watcher_disabled"}
        return await asyncio.to_thread(self._scan_watcher_sync, watcher, notify)

    def _scan_watcher_sync(
        self,
        watcher: WatcherConfig,
        notify: bool,
    ) -> dict[str, Any]:
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

    def _scan_watcher_unlocked_sync(
        self,
        watcher: WatcherConfig,
        notify: bool,
    ) -> dict[str, Any]:
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
            elif (
                previous.provider
                and current.provider != previous.provider
                and current.signature != previous.signature
            ):
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
                    rebaseline_reason = (
                        "provider_changed_with_non_equivalent_snapshot"
                    )
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
            event = (
                self._build_event(watcher, current, previous, diff)
                if changed
                else None
            )
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
                previous_results = (
                    pending.get("target_results")
                    if isinstance(pending.get("target_results"), dict)
                    else {}
                )
                enabled_target_names = [
                    target.name
                    for target in self.config.notify_targets
                    if target.enabled
                ]
                remaining_target_names = {
                    name
                    for name in enabled_target_names
                    if not isinstance(previous_results.get(name), dict)
                    or previous_results[name].get("ok") is not True
                }
                attempted_results = self._notify_targets(
                    event,
                    remaining_target_names,
                )
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
                    successful = len(
                        [
                            result
                            for result in event["notify_results"]
                            if result.get("ok") is True
                        ]
                    )
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
                            "created_at": pending.get("created_at")
                            or event["created_at"],
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

    def _render_message(
        self,
        watcher: WatcherConfig,
        snapshot: ShareSnapshot,
    ) -> str:
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
                    elif (
                        not isinstance(response_body, dict)
                        or response_body.get("ok") is not True
                    ):
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

    async def send_test_event(
        self,
        watcher_id: str | None = None,
    ) -> dict[str, Any]:
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
            "diff": {
                "added": [asdict(fake_file)],
                "removed": [],
                "changed": [],
            },
            "files": [asdict(fake_file)],
        }
        event["event_id"] = event["id"]
        event["notify_results"] = await asyncio.to_thread(
            self._notify_targets,
            event,
        )
        enabled_target_count = len(
            [target for target in self.config.notify_targets if target.enabled]
        )
        successful = len(
            [
                result
                for result in event["notify_results"]
                if result.get("ok") is True
            ]
        )
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
