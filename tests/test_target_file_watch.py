from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server.providers import FileEntry
from services.target_file_watch_service import (
    ResolvedTargetFile,
    TargetFileWatchError,
    TargetFileWatchService,
    _choose_target_file,
    _direct_candidates,
)


class FakeResolver:
    def __init__(self, current: ResolvedTargetFile):
        self.current = current
        self.delivery_calls = 0

    def resolve_metadata(self, _source_url: str) -> ResolvedTargetFile:
        return self.current

    def resolve_for_delivery(self, _source_url: str, fingerprint: str) -> ResolvedTargetFile:
        self.delivery_calls += 1
        if fingerprint != self.current.fingerprint:
            raise AssertionError("stale fingerprint passed to resolver")
        return ResolvedTargetFile(
            **{
                **self.current.__dict__,
                "direct_url": "https://download.example.invalid/fresh.bin",
            }
        )


def resolved(version: str, name: str = "package.zip") -> ResolvedTargetFile:
    return ResolvedTargetFile(
        fingerprint=f"sha256:{version}",
        stable_id=f"file-{version}",
        name=name,
        size="10 MB",
        modified_time=f"2026-08-0{version}",
        share_link="https://abc.lanzou.com/iTEST",
        provider="lanzou_web",
    )


class TargetFileWatchServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_path = root / "target-file-watch.json"
        self.state_path = root / "target-file-watch-state.json"
        self.env = patch.dict(
            os.environ,
            {
                "TARGET_FILE_WATCH_CONFIG_PATH": str(self.config_path),
                "TARGET_FILE_WATCH_STATE_PATH": str(self.state_path),
            },
            clear=False,
        )
        self.env.start()
        self.service = TargetFileWatchService()
        self.service.save_config(
            {
                "enabled": True,
                "source_url": "https://abc.lanzou.com/iTEST",
                "callback_url": "http://192.168.3.89:6108/api/target-file-push/event",
                "callback_token": "0123456789abcdef0123456789abcdef",
                "check_interval_seconds": 300,
            }
        )

    async def asyncTearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    async def test_first_check_only_baselines_then_change_delivers(self) -> None:
        fake = FakeResolver(resolved("1"))
        self.service.resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}

        first = await self.service.check_once()
        self.assertEqual(first["state"], "baselined")
        self.assertFalse(first["uploaded"])
        self.assertEqual(deliveries, [])
        self.assertEqual(fake.delivery_calls, 0)

        second = await self.service.check_once()
        self.assertEqual(second["state"], "unchanged")
        self.assertEqual(deliveries, [])

        fake.current = resolved("2")
        third = await self.service.check_once()
        self.assertEqual(third["state"], "delivered")
        self.assertTrue(third["uploaded"])
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["schema"], "target-file-push.v1")
        self.assertEqual(deliveries[0]["fingerprint"], "sha256:2")
        self.assertEqual(deliveries[0]["direct_url"], "https://download.example.invalid/fresh.bin")
        self.assertEqual(self.service.status()["baseline"]["fingerprint"], "sha256:2")

    async def test_callback_failure_does_not_advance_baseline(self) -> None:
        fake = FakeResolver(resolved("1"))
        self.service.resolver = fake
        self.service._deliver = lambda _payload: {"ok": True}
        await self.service.check_once()
        self.assertEqual(self.service.status()["baseline"]["fingerprint"], "sha256:1")

        fake.current = resolved("2")

        def fail(_payload):
            raise TargetFileWatchError("callback failed")

        self.service._deliver = fail
        with self.assertRaises(TargetFileWatchError):
            await self.service.check_once()
        status = self.service.status()
        self.assertEqual(status["baseline"]["fingerprint"], "sha256:1")
        self.assertEqual(status["pending"]["fingerprint"], "sha256:2")

    async def test_source_url_change_resets_baseline(self) -> None:
        fake = FakeResolver(resolved("1"))
        self.service.resolver = fake
        self.service._deliver = lambda _payload: {"ok": True}
        await self.service.check_once()
        self.assertIsNotNone(self.service.status()["baseline"])

        self.service.save_config(
            {
                "enabled": True,
                "source_url": "https://xyz.lanzou.com/iNEXT",
                "callback_url": "http://192.168.3.89:6108/api/target-file-push/event",
                "callback_token": "0123456789abcdef0123456789abcdef",
            }
        )
        self.assertIsNone(self.service.status()["baseline"])

    def test_multi_file_share_is_not_guessed(self) -> None:
        files = [
            FileEntry(id="a", name="a.zip", link="https://abc.lanzou.com/ia"),
            FileEntry(id="b", name="b.zip", link="https://abc.lanzou.com/ib"),
        ]
        with self.assertRaises(TargetFileWatchError):
            _choose_target_file("https://abc.lanzou.com/folder", files)

    def test_direct_url_candidates_prefer_download_fields(self) -> None:
        item = FileEntry(
            id="a",
            name="a.zip",
            link="https://abc.lanzou.com/ia",
            raw={
                "url": "https://abc.lanzou.com/ia",
                "downurl": "https://download.example.invalid/a.zip?sign=fresh",
            },
        )
        candidates = _direct_candidates(item)
        self.assertEqual(candidates[0], "https://download.example.invalid/a.zip?sign=fresh")


if __name__ == "__main__":
    unittest.main()
