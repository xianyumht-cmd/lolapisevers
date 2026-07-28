import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.persistent_snapshot_store import PersistentSnapshotStore


class PersistentSnapshotStoreTests(unittest.TestCase):
    def test_save_and_load_unicode_payload_with_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            payload = {"hero": "滑板鞋", "rows": [{"name": "合集一", "pick_rate": 0.12}]}
            saved = store.save(
                "lol.shards",
                payload,
                {"source_etag": '"abc"', "source_last_modified": "Mon, 27 Jul 2026 12:00:00 GMT"},
            )
            loaded = store.load("lol.shards", max_age_seconds=60)

            self.assertTrue(saved["ok"])
            self.assertEqual(saved["status"], "saved")
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.status, "hit")
            self.assertEqual(loaded.payload, payload)
            self.assertEqual(loaded.metadata["source_etag"], '"abc"')
            self.assertEqual(len(loaded.content_sha256), 64)

    def test_source_id_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            for value in ("../secret", "a/b", "", ".hidden"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        store.save(value, {"ok": True})

    def test_expired_snapshot_is_not_returned_as_usable_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            old = datetime.now(timezone.utc) - timedelta(hours=2)
            store.save("lol.heroes", {"hero": []}, captured_at=old)

            loaded = store.load("lol.heroes", max_age_seconds=60)

            self.assertFalse(loaded.ok)
            self.assertEqual(loaded.status, "expired")
            self.assertIsNone(loaded.payload)
            self.assertGreaterEqual(loaded.age_seconds, 60)

    def test_hash_mismatch_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = PersistentSnapshotStore(root)
            store.save("lol.shards", {"version": 1})
            path = store.path_for("lol.shards")
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"] = {"version": 2}
            path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

            loaded = store.load("lol.shards")

            self.assertFalse(loaded.ok)
            self.assertEqual(loaded.status, "corrupt")
            self.assertIn("hash mismatch", loaded.error)
            self.assertFalse(path.exists())
            self.assertTrue(loaded.quarantined_path)
            self.assertTrue(Path(loaded.quarantined_path).is_file())

    def test_invalid_json_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            path = store.path_for("lol.heroes")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")

            loaded = store.load("lol.heroes")

            self.assertFalse(loaded.ok)
            self.assertEqual(loaded.status, "corrupt")
            self.assertTrue(Path(loaded.quarantined_path).is_file())

    def test_incompatible_schema_is_preserved_for_future_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            path = store.path_for("lol.heroes")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 999,
                        "source_id": "lol.heroes",
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "content_sha256": "unused",
                        "payload": {},
                        "metadata": {},
                    }
                ),
                encoding="utf-8",
            )

            loaded = store.load("lol.heroes")

            self.assertFalse(loaded.ok)
            self.assertEqual(loaded.status, "incompatible")
            self.assertTrue(path.is_file())
            self.assertFalse(loaded.quarantined_path)

    def test_failed_replace_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save("lol.shards", {"version": 1})
            original_bytes = store.path_for("lol.shards").read_bytes()

            with patch("services.persistent_snapshot_store.os.replace", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    store.save("lol.shards", {"version": 2})

            self.assertEqual(store.path_for("lol.shards").read_bytes(), original_bytes)
            loaded = store.load("lol.shards")
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.payload, {"version": 1})
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_concurrent_writes_leave_one_valid_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            payloads = [{"writer": index, "data": [index] * 20} for index in range(24)]

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda payload: store.save("lol.shards", payload), payloads))

            self.assertTrue(all(result["ok"] for result in results))
            loaded = store.load("lol.shards")
            self.assertTrue(loaded.ok)
            self.assertIn(loaded.payload, payloads)
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_refresh_error_is_recorded_and_cleared_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save("lol.shards", {"version": 1})
            recorded = store.record_refresh_error(
                "lol.shards",
                "read_timeout",
                "upstream request timed out\nsecret details removed by caller",
            )
            before = store.status("lol.shards", max_age_seconds=60)

            self.assertTrue(recorded["ok"])
            self.assertEqual(before["last_refresh_error_class"], "read_timeout")
            self.assertNotIn("\n", before["last_refresh_error_message"])

            store.save("lol.shards", {"version": 2})
            after = store.status("lol.shards", max_age_seconds=60)

            self.assertTrue(after["snapshot_ok"])
            self.assertEqual(after["last_refresh_error_class"], "")
            self.assertEqual(after["last_refresh_error_at"], "")
            self.assertTrue(after["last_success_at"])

    def test_non_json_payload_is_rejected_before_existing_file_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save("lol.shards", {"version": 1})
            original = store.path_for("lol.shards").read_bytes()

            with self.assertRaises(TypeError):
                store.save("lol.shards", {"bad": object()})

            self.assertEqual(store.path_for("lol.shards").read_bytes(), original)

    def test_environment_can_override_default_root(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"UPSTREAM_SNAPSHOT_DIR": temp}):
                store = PersistentSnapshotStore()
                store.save("lol.shards", {"version": 1})
                self.assertEqual(store.root, Path(temp).resolve())
                self.assertTrue((Path(temp) / "lol.shards.json").is_file())


if __name__ == "__main__":
    unittest.main()
