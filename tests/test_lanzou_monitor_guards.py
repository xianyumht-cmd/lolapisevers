import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lanzou_update_push_api_server.config import AppConfig, NotifyTargetConfig, WatcherConfig
from lanzou_update_push_api_server.monitor import LanzouMonitorService, StateStore, compare_snapshots
from lanzou_update_push_api_server.providers import FileEntry, ProviderChain, ShareSnapshot
from lanzou_update_push_api_server.state_recovery import default_state


def make_snapshot(
    files,
    *,
    watcher_id="demo",
    url="https://example.test",
    provider="test",
):
    return ShareSnapshot(
        watcher_id=watcher_id,
        title=watcher_id.title(),
        url=url,
        provider=provider,
        fetched_at="2026-01-01T00:00:00+00:00",
        files=files,
    )


class LanzouMonitorGuardTests(unittest.TestCase):
    def test_canonical_identity_ignores_provider_specific_id_and_link(self):
        native = make_snapshot(
            [
                FileEntry(
                    id="native-123",
                    name="Release.zip",
                    size="1 M",
                    link="https://lanzou.test/native-123",
                )
            ],
            provider="lanzou_web",
        )
        api = make_snapshot(
            [
                FileEntry(
                    id="api-987",
                    name=" release.zip ",
                    size="1 M",
                    link="https://download.test/token",
                )
            ],
            provider="wer_api",
        )

        self.assertEqual(native.signature, api.signature)
        self.assertEqual(
            compare_snapshots(native, api),
            {"added": [], "removed": [], "changed": []},
        )

    def test_same_provider_replacement_with_same_name_and_size_is_detected(self):
        previous = make_snapshot(
            [
                FileEntry(
                    id="old-id",
                    name="Release.zip",
                    size="1 M",
                    link="https://lanzou.test/old-id",
                )
            ],
            provider="lanzou_web",
        )
        current = make_snapshot(
            [
                FileEntry(
                    id="new-id",
                    name="Release.zip",
                    size="1 M",
                    link="https://lanzou.test/new-id",
                )
            ],
            provider="lanzou_web",
        )

        diff = compare_snapshots(previous, current)

        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(len(diff["changed"]), 1)
        self.assertNotEqual(
            previous.provider_signature,
            current.provider_signature,
        )

    def test_provider_chain_rejects_empty_snapshot_and_uses_fallback(self):
        watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
        config = AppConfig(provider_order=["lanzou_web", "wer_api"], watchers=[watcher])
        chain = ProviderChain(config)
        calls = []

        class EmptyProvider:
            def fetch(self, _watcher, _config):
                calls.append("empty")
                return make_snapshot([], provider="lanzou_web")

        class WorkingProvider:
            def fetch(self, _watcher, _config):
                calls.append("working")
                return make_snapshot(
                    [FileEntry(id="api-id", name="release.zip")],
                    provider="wer_api",
                )

        chain.providers["lanzou_web"] = EmptyProvider()
        chain.providers["wer_api"] = WorkingProvider()

        result = chain.fetch(watcher)

        self.assertEqual(calls, ["empty", "working"])
        self.assertEqual(result.provider, "wer_api")
        self.assertEqual(len(result.files), 1)

    def test_empty_snapshot_never_replaces_non_empty_baseline(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            service = LanzouMonitorService(
                AppConfig(state_path=Path(temp_dir) / "state.json", watchers=[watcher])
            )
            previous = make_snapshot([FileEntry(id="old", name="release.zip")])
            service.store.set_snapshot(previous)

            class EmptyProvider:
                def fetch(self, _watcher):
                    return make_snapshot([])

            service.provider_chain = EmptyProvider()

            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertFalse(result["ok"])
            self.assertEqual(
                result["error_code"],
                "empty_snapshot_confirmation_pending",
            )
            self.assertTrue(result["guarded"])
            self.assertEqual(
                service.store.data["guard_candidates"]["demo"]["seen_count"],
                1,
            )
            self.assertEqual(service.store.snapshot_for("demo").signature, previous.signature)

    def test_confirmed_empty_snapshot_can_deliver_final_file_removal(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(
                id="demo",
                title="Demo",
                url="https://example.test",
            )
            service = LanzouMonitorService(
                AppConfig(
                    state_path=Path(temp_dir) / "state.json",
                    watchers=[watcher],
                    notify_targets=[
                        NotifyTargetConfig(
                            name="webhook",
                            url="https://notify.test",
                        )
                    ],
                )
            )
            previous = make_snapshot(
                [FileEntry(id="old", name="release.zip")],
            )
            current = make_snapshot([])
            service.store.set_snapshot(previous)

            class EmptyProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = EmptyProvider()
            service._notify_targets = lambda _event, *_names: [
                {
                    "target": "webhook",
                    "ok": True,
                    "delivery_state": "complete",
                }
            ]

            first = asyncio.run(
                service.scan_watcher("demo", notify=True)
            )
            second = asyncio.run(
                service.scan_watcher("demo", notify=True)
            )

            self.assertTrue(first["guarded"])
            self.assertTrue(second["snapshot_committed"])
            self.assertEqual(second["event"]["delivery_state"], "complete")
            self.assertEqual(second["diff"]["removed"][0]["name"], "release.zip")
            self.assertEqual(service.store.snapshot_for("demo").files, [])

    def test_url_change_rebaselines_without_notification(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://new.example.test")
            service = LanzouMonitorService(
                AppConfig(
                    state_path=Path(temp_dir) / "state.json",
                    watchers=[watcher],
                    notify_targets=[NotifyTargetConfig(name="webhook", url="https://notify.test")],
                )
            )
            previous = make_snapshot(
                [FileEntry(id="old", name="old.zip")],
                url="https://old.example.test",
                provider="lanzou_web",
            )
            current = make_snapshot(
                [FileEntry(id="new", name="new.zip")],
                url=watcher.url,
                provider="lanzou_web",
            )
            service.store.set_snapshot(previous)

            class StaticProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = StaticProvider()
            notifications = []
            service._notify_targets = lambda event, *_names: notifications.append(event) or []

            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertTrue(result["ok"])
            self.assertTrue(result["rebaseline"])
            self.assertEqual(result["rebaseline_reason"], "watcher_url_changed")
            self.assertTrue(result["notification_suppressed"])
            self.assertEqual(notifications, [])
            self.assertEqual(service.store.snapshot_for("demo").signature, current.signature)

    def test_provider_switch_with_non_equivalent_result_rebaselines(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            service = LanzouMonitorService(
                AppConfig(
                    state_path=Path(temp_dir) / "state.json",
                    watchers=[watcher],
                    notify_targets=[NotifyTargetConfig(name="webhook", url="https://notify.test")],
                )
            )
            previous = make_snapshot(
                [FileEntry(id="native", name="old.zip")],
                provider="lanzou_web",
            )
            current = make_snapshot(
                [FileEntry(id="api", name="new.zip")],
                provider="wer_api",
            )
            service.store.set_snapshot(previous)

            class StaticProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = StaticProvider()
            notifications = []
            service._notify_targets = lambda event, *_names: notifications.append(event) or []

            first = asyncio.run(service.scan_watcher("demo", notify=True))
            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertFalse(first["ok"])
            self.assertTrue(first["guarded"])
            self.assertEqual(first["guard_kind"], "provider_switch")
            self.assertTrue(result["rebaseline"])
            self.assertEqual(
                result["rebaseline_reason"],
                "provider_changed_with_non_equivalent_snapshot",
            )
            self.assertEqual(notifications, [])

    def test_removed_watcher_state_is_archived_idempotently_and_restored(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            service = LanzouMonitorService(AppConfig(state_path=path, watchers=[watcher]))
            previous = make_snapshot([FileEntry(id="old", name="old.zip")])
            service.store.set_snapshot(previous)
            service.store.set_pending_delivery(
                "event-1",
                {"event_id": "event-1", "watcher_id": "demo", "target_results": {}},
            )

            service.reload_config(AppConfig(state_path=path, watchers=[]))
            first_archive = json.loads(json.dumps(service.store.data["orphaned_watchers"]["demo"]))
            service.reload_config(AppConfig(state_path=path, watchers=[]))

            self.assertEqual(service.store.data["version"], 6)
            self.assertNotIn("demo", service.store.data["snapshots"])
            self.assertNotIn("demo", service.store.data["last_scan"])
            self.assertNotIn("event-1", service.store.data["pending_deliveries"])
            self.assertEqual(service.store.data["orphaned_watchers"]["demo"], first_archive)

            service.reload_config(AppConfig(state_path=path, watchers=[watcher]))

            self.assertNotIn("demo", service.store.data["orphaned_watchers"])
            self.assertEqual(service.store.snapshot_for("demo").signature, previous.signature)
            self.assertIn("event-1", service.store.data["pending_deliveries"])

    def test_status_reports_counts_and_degraded_state(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            failed = WatcherConfig(id="failed", title="Failed", url="https://failed.test")
            pending = WatcherConfig(id="pending", title="Pending", url="https://pending.test")
            never = WatcherConfig(id="never", title="Never", url="https://never.test")
            removed = WatcherConfig(id="removed", title="Removed", url="https://removed.test")
            service = LanzouMonitorService(
                AppConfig(state_path=path, watchers=[failed, pending, never, removed])
            )
            service.store.set_scan_error(
                "failed",
                {
                    "error_code": "provider_unavailable",
                    "error_class": "ProviderError",
                    "retryable": True,
                },
            )
            service.store.set_snapshot(
                make_snapshot(
                    [FileEntry(id="pending", name="pending.zip")],
                    watcher_id="pending",
                    url=pending.url,
                )
            )
            service.store.set_pending_delivery(
                "event-pending",
                {"event_id": "event-pending", "watcher_id": "pending", "target_results": {}},
            )
            service.store.set_snapshot(
                make_snapshot(
                    [FileEntry(id="removed", name="removed.zip")],
                    watcher_id="removed",
                    url=removed.url,
                )
            )
            service.reload_config(AppConfig(state_path=path, watchers=[failed, pending, never]))

            status = service.status()

            self.assertEqual(
                status["watchers"],
                {
                    "enabled": 3,
                    "failed": 1,
                    "pending": 1,
                    "never_scanned": 1,
                    "orphan": 1,
                    "guarded": 0,
                },
            )
            self.assertFalse(status["ok"])
            self.assertFalse(status["ready"])
            self.assertTrue(status["degraded"])
            self.assertEqual(status["status"], "degraded")
            self.assertIn("failed", status["degraded_reasons"])
            self.assertIn("orphan", status["degraded_reasons"])

    def test_status_is_ready_after_successful_baseline_while_loop_runs(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            service = LanzouMonitorService(
                AppConfig(state_path=Path(temp_dir) / "state.json", watchers=[watcher])
            )
            service.store.set_snapshot(make_snapshot([FileEntry(id="a", name="a.zip")]))

            class RunningTask:
                @staticmethod
                def done():
                    return False

            service._task = RunningTask()
            status = service.status()

            self.assertTrue(status["ok"])
            self.assertTrue(status["ready"])
            self.assertFalse(status["degraded"])
            self.assertEqual(status["status"], "ready")

    def test_default_state_uses_orphan_aware_schema(self):
        state = default_state()

        self.assertEqual(state["version"], 6)
        self.assertEqual(state["orphaned_watchers"], {})
        self.assertEqual(state["guard_candidates"], {})
        self.assertEqual(state["content_risk"], {})

    def test_existing_state_schema_is_migrated_on_load(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "snapshots": {},
                        "events": [],
                        "last_scan": {},
                        "pending_deliveries": {},
                    }
                ),
                encoding="utf-8",
            )

            StateStore(path)
            migrated = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(migrated["version"], 6)
            self.assertEqual(migrated["orphaned_watchers"], {})


if __name__ == "__main__":
    unittest.main()
