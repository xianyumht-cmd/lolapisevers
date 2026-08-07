from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.target_file_watch_directory import DirectoryResolvedFile, DirectorySnapshot
from services.target_file_watch_runtime import SafeTargetFileWatchService
from services.target_file_watch_service import ResolvedTargetFile, TargetFileWatchError


SOURCE_URL = "https://wwbvf.lanzn.com/b016kzvvmd"


def resolved(name: str, version: str) -> DirectoryResolvedFile:
    return DirectoryResolvedFile(
        key=f"name:{name.casefold()}",
        file=ResolvedTargetFile(
            fingerprint=f"sha256:{name}:{version}",
            stable_id=f"{name}-{version}",
            name=name,
            size=f"{version} MB",
            modified_time=f"2026-08-0{version}",
            share_link=f"https://wwbvf.lanzn.com/i{name}{version}",
            provider="lanzou_web",
        ),
    )


class FakeDirectoryResolver:
    def __init__(self, files: list[DirectoryResolvedFile]):
        self.files = files
        self.delivery_calls: list[tuple[str, str]] = []

    def resolve_snapshot(self, _source_url: str) -> DirectorySnapshot:
        return DirectorySnapshot(provider="lanzou_web", files=tuple(self.files))

    def resolve_for_delivery(self, _source_url: str, key: str, fingerprint: str) -> ResolvedTargetFile:
        self.delivery_calls.append((key, fingerprint))
        match = next(item for item in self.files if item.key == key)
        if match.file.fingerprint != fingerprint:
            raise TargetFileWatchError("stale")
        return ResolvedTargetFile(**{**match.file.__dict__, "direct_url": f"https://download.example.invalid/{match.file.name}"})


class TargetFileWatchDirectoryTest(unittest.IsolatedAsyncioTestCase):
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
        self.service = SafeTargetFileWatchService()
        self.service.save_config(
            {
                "enabled": True,
                "source_url": SOURCE_URL,
                "callback_url": "http://192.168.3.89:6108/api/target-file-push/event",
                "callback_token": "0123456789abcdef0123456789abcdef",
                "check_interval_seconds": 300,
            }
        )

    async def asyncTearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    async def test_first_folder_snapshot_only_baselines_then_added_file_delivers(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1"), resolved("B.zip", "1")])
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}

        first = await self.service.check_once()
        self.assertEqual(first["state"], "baselined")
        self.assertEqual(first["file_count"], 2)
        self.assertFalse(first["uploaded"])
        self.assertEqual(deliveries, [])

        fake.files.append(resolved("C.zip", "1"))
        second = await self.service.check_once()
        self.assertEqual(second["state"], "delivered")
        self.assertEqual(second["uploaded_count"], 1)
        self.assertEqual(deliveries[0]["file"]["name"], "C.zip")
        self.assertEqual(self.service.status()["baseline"]["file_count"], 3)

    async def test_same_name_replacement_delivers_new_version(self) -> None:
        fake = FakeDirectoryResolver([resolved("Client.zip", "1")])
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()

        fake.files = [resolved("Client.zip", "2")]
        result = await self.service.check_once()
        self.assertEqual(result["uploaded_count"], 1)
        self.assertEqual(deliveries[-1]["fingerprint"], "sha256:Client.zip:2")

    async def test_removal_only_updates_baseline_without_upload(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1"), resolved("B.zip", "1")])
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()

        fake.files = [resolved("B.zip", "1")]
        result = await self.service.check_once()
        self.assertEqual(result["state"], "baseline_updated")
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(deliveries, [])
        self.assertEqual(self.service.status()["baseline"]["file_count"], 1)

    async def test_multiple_new_files_are_delivered_individually(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1")])
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()

        fake.files = [resolved("A.zip", "1"), resolved("B.zip", "1"), resolved("C.zip", "1")]
        result = await self.service.check_once()
        self.assertEqual(result["uploaded_count"], 2)
        self.assertEqual([item["file"]["name"] for item in deliveries], ["B.zip", "C.zip"])
        self.assertNotEqual(deliveries[0]["event_id"], deliveries[1]["event_id"])

    async def test_partial_batch_failure_never_advances_baseline(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1")])
        self.service.directory_resolver = fake
        await self.service.check_once()
        before = self.service.status()["baseline"]["signature"]

        fake.files = [resolved("A.zip", "1"), resolved("B.zip", "1"), resolved("C.zip", "1")]
        calls = 0

        def deliver(_payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TargetFileWatchError("simulated callback failure")
            return {"ok": True, "uploaded": True}

        self.service._deliver = deliver
        with self.assertRaisesRegex(TargetFileWatchError, "simulated callback failure"):
            await self.service.check_once()

        status = self.service.status()
        self.assertEqual(status["baseline"]["signature"], before)
        self.assertEqual(len(status["pending"]["events"]), 2)


if __name__ == "__main__":
    unittest.main()
