import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.lolban_service import (
    LOL_BAN_SNAPSHOT_SOURCE_ID,
    LolBanService,
)
from services.persistent_snapshot_store import PersistentSnapshotStore


def payload(qq: str, status: str = "正常"):
    return {
        "code": 200,
        "by": "test",
        "msg": "此账号状态正常" if status == "正常" else "此账号已被封禁",
        "data": {
            "qq": qq,
            "ban_time": "",
            "end_time": "账号状态正常" if status == "正常" else "1天",
            "status": status,
        },
    }


class FakeProvider:
    def __init__(self, name="primary", *, error=None, status="正常"):
        self.name = name
        self.error = error
        self.status = status
        self.calls = 0

    def query(self, qq):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return payload(qq, self.status)


class FailingSaveStore(PersistentSnapshotStore):
    def save(self, *args, **kwargs):
        raise OSError("disk full")


class LolBanPersistentFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_restores_last_known_result_after_provider_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            live_service = LolBanService(
                [FakeProvider()],
                stale_cache_seconds=3600,
                snapshot_store=store,
            )
            live, source, _ = await live_service.get_result("2621735529")

            self.assertEqual(source, "live")
            self.assertEqual(live["data"]["status"], "正常")
            saved = store.load(LOL_BAN_SNAPSHOT_SOURCE_ID)
            self.assertTrue(saved.ok)
            self.assertEqual(len(saved.payload["entries"]), 1)

            offline = FakeProvider(error=ConnectionError("provider offline"))
            restarted = LolBanService(
                [offline],
                stale_cache_seconds=3600,
                snapshot_store=store,
            )
            stale, source, ttl = await restarted.get_result("2621735529")

            self.assertEqual(source, "stale")
            self.assertEqual(ttl, 0)
            self.assertEqual(stale["data"]["status"], "正常")
            self.assertEqual(stale["stale_origin"], "persistent_snapshot")
            self.assertEqual(stale["fallback_reason"], "all_providers_failed")
            self.assertEqual(offline.calls, 1)
            health = restarted.health()
            self.assertEqual(health["persistent_snapshot_status"], "restored")
            self.assertEqual(
                health["persistent_snapshot_restored_entries"],
                1,
            )

    async def test_persistent_snapshot_preserves_existing_entry_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            service = LolBanService(
                [FakeProvider()],
                stale_cache_seconds=3600,
                max_stale_entries=2,
                snapshot_store=store,
            )

            await service.get_result("10001")
            await service.get_result("10002")
            await service.get_result("10003")

            saved = store.load(LOL_BAN_SNAPSHOT_SOURCE_ID)
            self.assertTrue(saved.ok)
            self.assertEqual(
                [item["qq"] for item in saved.payload["entries"]],
                ["10002", "10003"],
            )

            restarted = LolBanService(
                [],
                stale_cache_seconds=3600,
                max_stale_entries=2,
                snapshot_store=store,
            )
            self.assertEqual(restarted.health()["stale_cache_entries"], 2)
            with self.assertRaisesRegex(RuntimeError, "providers_not_configured"):
                await restarted.get_result("10001")
            stale, source, _ = await restarted.get_result("10003")
            self.assertEqual(source, "stale")
            self.assertEqual(stale["stale_origin"], "persistent_snapshot")

    async def test_expired_snapshot_is_not_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            service = LolBanService(
                [FakeProvider()],
                stale_cache_seconds=60,
                snapshot_store=store,
            )
            await service.get_result("2621735529")

            saved = store.load(LOL_BAN_SNAPSHOT_SOURCE_ID)
            old = datetime.now(timezone.utc) - timedelta(hours=1)
            store.save(
                LOL_BAN_SNAPSHOT_SOURCE_ID,
                saved.payload,
                captured_at=old,
            )

            restarted = LolBanService(
                [FakeProvider(error=TimeoutError("offline"))],
                stale_cache_seconds=60,
                snapshot_store=store,
            )
            self.assertEqual(
                restarted.health()["persistent_snapshot_status"],
                "expired",
            )
            with self.assertRaisesRegex(RuntimeError, "TimeoutError"):
                await restarted.get_result("2621735529")

    async def test_corrupt_snapshot_is_quarantined_and_live_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            path = store.path_for(LOL_BAN_SNAPSHOT_SOURCE_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")

            service = LolBanService(
                [FakeProvider()],
                stale_cache_seconds=3600,
                snapshot_store=store,
            )
            self.assertEqual(
                service.health()["persistent_snapshot_status"],
                "corrupt",
            )
            result, source, _ = await service.get_result("2621735529")

            self.assertEqual(source, "live")
            self.assertEqual(result["data"]["status"], "正常")
            self.assertTrue(path.is_file())
            self.assertTrue(
                list(Path(temp).glob("lolban-last-known-v1.bad.*.json"))
            )

    async def test_unsafe_or_mismatched_snapshot_entry_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save(
                LOL_BAN_SNAPSHOT_SOURCE_ID,
                {
                    "entries": [
                        {
                            "qq": "2621735529",
                            "captured_at_epoch": 9999999999,
                            "payload": {
                                **payload("10001"),
                                "msg": "请访问 https://unsafe.example",
                            },
                        }
                    ],
                    "max_entries": 1024,
                },
            )

            service = LolBanService(
                [],
                stale_cache_seconds=3600,
                snapshot_store=store,
            )
            self.assertEqual(service.health()["stale_cache_entries"], 0)
            self.assertEqual(
                service.health()["persistent_snapshot_status"],
                "empty",
            )
            with self.assertRaisesRegex(RuntimeError, "providers_not_configured"):
                await service.get_result("2621735529")

    async def test_snapshot_write_failure_does_not_hide_live_result(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FailingSaveStore(Path(temp))
            service = LolBanService(
                [FakeProvider(status="封禁")],
                stale_cache_seconds=3600,
                snapshot_store=store,
            )

            result, source, ttl = await service.get_result("2621735529")

            self.assertEqual(source, "live")
            self.assertEqual(result["data"]["status"], "封禁")
            self.assertEqual(ttl, service.banned_cache_seconds)
            self.assertEqual(result["snapshot_write_error"], "OSError")
            health = service.health()
            self.assertEqual(health["persistent_snapshot_status"], "write_error")
            self.assertEqual(
                health["persistent_snapshot_write_error_class"],
                "OSError",
            )


if __name__ == "__main__":
    unittest.main()
