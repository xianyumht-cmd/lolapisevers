import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from lanzou_update_push_api_server.config import (
    AppConfig,
    NotifyTargetConfig,
    WatcherConfig,
)
from lanzou_update_push_api_server.monitor import LanzouMonitorService, StateStore
from lanzou_update_push_api_server.providers import FileEntry, ShareSnapshot


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def snapshot(name: str) -> ShareSnapshot:
    return ShareSnapshot(
        watcher_id="demo",
        title="Demo",
        url="https://share.invalid",
        provider="test",
        fetched_at="2026-07-26T00:00:00+00:00",
        files=[
            FileEntry(
                id=name,
                name=f"{name}.zip",
                size="1 MB",
                link=f"https://share.invalid/{name}",
            )
        ],
    )


class LanzouDeliverySecurityTests(unittest.TestCase):
    def make_service(self, temp_dir: str, targets=None) -> LanzouMonitorService:
        watcher = WatcherConfig(
            id="demo",
            title="Demo",
            url="https://share.invalid",
        )
        return LanzouMonitorService(
            AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=targets
                or [
                    NotifyTargetConfig(
                        name="groupguard",
                        url="https://callback.invalid/event",
                    )
                ],
            )
        )

    def test_callback_requires_complete_delivery_receipt(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)
            with patch(
                "lanzou_update_push_api_server.monitor.requests.post",
                return_value=FakeResponse(
                    {"ok": True, "deliveryState": "partial"},
                ),
            ):
                result = service._notify_targets({"id": "event-1"})

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["ok"])
        self.assertFalse(result[0]["acknowledged"])
        self.assertEqual(
            result[0]["error_code"],
            "callback_delivery_incomplete",
        )

    def test_complete_delivery_receipt_is_acknowledged(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)
            with patch(
                "lanzou_update_push_api_server.monitor.requests.post",
                return_value=FakeResponse(
                    {"ok": True, "deliveryState": "complete"},
                ),
            ):
                result = service._notify_targets({"id": "event-1"})

        self.assertTrue(result[0]["ok"])
        self.assertTrue(result[0]["acknowledged"])
        self.assertNotIn("error_code", result[0])

    def test_unrecognized_delivery_state_is_not_copied_from_response(self):
        marker = "credential-marker"
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)
            with patch(
                "lanzou_update_push_api_server.monitor.requests.post",
                return_value=FakeResponse(
                    {
                        "ok": True,
                        "deliveryState": marker,
                    },
                ),
            ):
                result = service._notify_targets({"id": "event-1"})

        self.assertFalse(result[0]["ok"])
        self.assertEqual(result[0]["delivery_state"], "")
        self.assertNotIn(marker, json.dumps(result))

    def test_transport_exception_is_structured_without_original_context(self):
        marker = "credential-marker"
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)
            with patch(
                "lanzou_update_push_api_server.monitor.requests.post",
                side_effect=requests.ConnectTimeout(
                    f"https://callback.invalid/event?access={marker}",
                ),
            ):
                result = service._notify_targets({"id": "event-1"})
            service.store.set_pending_delivery(
                "event-1",
                {
                    "event_id": "event-1",
                    "watcher_id": "demo",
                    "target_results": {"groupguard": result[0]},
                },
            )
            persisted = service.store.path.read_text(encoding="utf-8")

        self.assertEqual(result[0]["error_code"], "connect_timeout")
        self.assertEqual(result[0]["error_class"], "ConnectTimeout")
        self.assertNotIn("error", result[0])
        self.assertNotIn(marker, persisted)
        self.assertNotIn("callback.invalid", persisted)

    def test_state_load_redacts_legacy_error_context_recursively(self):
        marker = "credential-marker"
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "snapshots": {},
                        "last_scan": {
                            "demo": {
                                "ok": False,
                                "error": f"timeout https://host.invalid/?token={marker}",
                            }
                        },
                        "events": [
                            {
                                "id": "event-1",
                                "notify_results": [
                                    {
                                        "target": "groupguard",
                                        "ok": False,
                                        "error": marker,
                                        "url": f"https://host.invalid/?token={marker}",
                                        "headers": {"authorization": marker},
                                        "body": marker,
                                    }
                                ],
                            }
                        ],
                        "pending_deliveries": {
                            "event-1": {
                                "watcher_id": "demo",
                                "target_results": {
                                    "groupguard": {
                                        "ok": False,
                                        "error": marker,
                                        "query": {"token": marker},
                                    }
                                },
                            }
                        },
                        "orphaned_watchers": {
                            "old": {
                                "last_scan": {
                                    "ok": False,
                                    "error": marker,
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = StateStore(path)
            persisted = path.read_text(encoding="utf-8")

        self.assertEqual(store.data["version"], 6)
        self.assertNotIn(marker, persisted)
        self.assertNotIn(
            "error",
            store.data["last_scan"]["demo"],
        )
        self.assertEqual(
            store.data["last_scan"]["demo"]["error_code"],
            "legacy_error_redacted",
        )
        migrated_result = store.data["events"][0]["notify_results"][0]
        self.assertNotIn("url", migrated_result)
        self.assertNotIn("headers", migrated_result)
        self.assertNotIn("body", migrated_result)

    def test_new_event_supersedes_old_pending_delivery_for_watcher(self):
        with TemporaryDirectory() as temp_dir:
            targets = [
                NotifyTargetConfig(
                    name="groupguard-a",
                    url="https://callback-a.invalid/event",
                ),
                NotifyTargetConfig(
                    name="groupguard-b",
                    url="https://callback-b.invalid/event",
                ),
            ]
            service = self.make_service(temp_dir, targets)
            service.store.set_snapshot(snapshot("base"))

            class MutableProvider:
                current = snapshot("next")

                def fetch(self, _watcher):
                    return self.current

            provider = MutableProvider()
            service.provider_chain = provider
            call_count = 0

            def notify(_event, target_names):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return [
                        {"target": name, "ok": name == "groupguard-a"}
                        for name in sorted(target_names)
                    ]
                return [
                    {"target": name, "ok": True}
                    for name in sorted(target_names)
                ]

            service._notify_targets = notify
            first = asyncio.run(
                service.scan_watcher("demo", notify=True)
            )
            provider.current = snapshot("latest")
            second = asyncio.run(
                service.scan_watcher("demo", notify=True)
            )

            events = {
                event["id"]: event
                for event in service.store.recent_events()
            }

        self.assertEqual(first["event"]["delivery_state"], "partial")
        self.assertTrue(second["snapshot_committed"])
        self.assertEqual(service.store.data["pending_deliveries"], {})
        self.assertEqual(
            events[first["event"]["id"]]["delivery_state"],
            "superseded",
        )
        self.assertEqual(
            events[first["event"]["id"]]["superseded_by_event_id"],
            second["event"]["id"],
        )

    def test_notify_target_names_must_be_non_empty_and_unique(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            AppConfig(
                notify_targets=[
                    NotifyTargetConfig(
                        name="",
                        url="https://callback.invalid",
                    )
                ]
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            AppConfig(
                notify_targets=[
                    NotifyTargetConfig(
                        name="groupguard",
                        url="https://callback-a.invalid",
                    ),
                    NotifyTargetConfig(
                        name="groupguard",
                        url="https://callback-b.invalid",
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
