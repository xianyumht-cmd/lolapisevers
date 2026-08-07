from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lanzou_update_push_api_server.providers import FileEntry
from services.target_file_watch_directory import (
    DirectoryLanzouResolver,
    DirectoryResolvedFile,
    DirectorySnapshot,
    TargetFileDirectResolver,
    TargetFileWatchProviderConfig,
)
from services.target_file_watch_runtime import SafeTargetFileWatchService
from services.target_file_watch_service import ResolvedTargetFile, TargetFileWatchError


SOURCE_URL = "https://wwbvf.lanzn.com/b016kzvvmd"


def resolved(name: str, version: str, *, provider_fingerprint: str = "") -> DirectoryResolvedFile:
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
        provider_fingerprint=provider_fingerprint,
    )


def provider_only_replacement(provider_fingerprint: str) -> DirectoryResolvedFile:
    return DirectoryResolvedFile(
        key="name:client.zip",
        file=ResolvedTargetFile(
            fingerprint="sha256:canonical-same",
            stable_id="provider-specific-id",
            name="Client.zip",
            size="10 MB",
            modified_time="",
            share_link="https://wwbvf.lanzn.com/iClient",
            provider="lanzou_web",
        ),
        provider_fingerprint=provider_fingerprint,
    )


class FakeDirectoryResolver:
    def __init__(self, files: list[DirectoryResolvedFile], provider: str = "lanzou_web"):
        self.files = files
        self.provider = provider
        self.delivery_calls: list[tuple[str, str]] = []

    def resolve_snapshot(self, _source_url: str) -> DirectorySnapshot:
        return DirectorySnapshot(provider=self.provider, files=tuple(self.files))

    def resolve_for_delivery(self, _source_url: str, key: str, fingerprint: str) -> ResolvedTargetFile:
        self.delivery_calls.append((key, fingerprint))
        match = next(item for item in self.files if item.key == key)
        if match.file.fingerprint != fingerprint:
            raise TargetFileWatchError("stale")
        return ResolvedTargetFile(**{**match.file.__dict__, "direct_url": f"https://download.example.invalid/{match.file.name}"})


class RecordingDirectResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.return_url: str | None = None

    def resolve(self, share_link: str) -> str:
        self.calls.append(share_link)
        if self.error is not None:
            raise self.error
        if self.return_url is not None:
            return self.return_url
        return f"https://download.example.invalid/file-{len(self.calls)}.bin"


class LiveDirectoryResolver(DirectoryLanzouResolver):
    def __init__(self, files: list[DirectoryResolvedFile], direct: RecordingDirectResolver) -> None:
        super().__init__(direct_resolver=direct)
        self.files = files
        self.provider = "lanzou_web"

    def resolve_snapshot(self, _source_url: str) -> DirectorySnapshot:
        return DirectorySnapshot(provider=self.provider, files=tuple(self.files))


class FakeSnapshotProvider:
    def __init__(self, name: str, files: list[FileEntry], *, fail: Exception | None = None) -> None:
        self.name = name
        self.files = files
        self.fail = fail
        self.calls: list[str] = []

    def fetch(self, watcher, _config):
        self.calls.append(watcher.url)
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(provider=self.name, files=list(self.files))


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

    async def test_same_name_replacement_uses_latest_share_link(self) -> None:
        direct = RecordingDirectResolver()
        live = LiveDirectoryResolver([resolved("Client.zip", "1")], direct)
        self.service.directory_resolver = live
        self.service._deliver = lambda _payload: {"ok": True, "uploaded": True}
        await self.service.check_once()

        latest = resolved("Client.zip", "2")
        live.files = [latest]
        result = await self.service.check_once()

        self.assertEqual(result["state"], "delivered")
        self.assertEqual(direct.calls, [latest.file.share_link])

    async def test_same_provider_id_change_detected_when_name_size_and_canonical_fingerprint_are_same(self) -> None:
        fake = FakeDirectoryResolver([provider_only_replacement("sha256:provider-old")])
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()
        first_event_count = len(deliveries)

        fake.files = [provider_only_replacement("sha256:provider-new")]
        result = await self.service.check_once()

        self.assertEqual(result["state"], "delivered")
        self.assertEqual(result["uploaded_count"], 1)
        self.assertEqual(len(deliveries), first_event_count + 1)
        self.assertNotEqual(deliveries[-1]["fingerprint"], "sha256:canonical-same")
        self.assertEqual(fake.delivery_calls[-1][1], "sha256:canonical-same")

    async def test_provider_switch_with_different_snapshot_is_guarded_then_rebaselined_without_upload(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1")], provider="lanzou_web")
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()

        fake.provider = "wer_api"
        fake.files = [resolved("A.zip", "1"), resolved("B.zip", "1")]
        first = await self.service.check_once()
        second = await self.service.check_once()

        self.assertEqual(first["state"], "provider_switch_guarded")
        self.assertTrue(first["guarded"])
        self.assertEqual(second["state"], "rebaselined_provider_switch")
        self.assertFalse(second["uploaded"])
        self.assertEqual(deliveries, [])
        self.assertEqual(self.service.status()["baseline"]["provider"], "wer_api")
        self.assertEqual(self.service.status()["baseline"]["file_count"], 2)

    async def test_equivalent_provider_switch_does_not_create_false_update(self) -> None:
        fake = FakeDirectoryResolver([resolved("A.zip", "1")], provider="lanzou_web")
        self.service.directory_resolver = fake
        deliveries: list[dict] = []
        self.service._deliver = lambda payload: deliveries.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()

        fake.provider = "wer_api"
        result = await self.service.check_once()
        self.assertEqual(result["state"], "baseline_updated")
        self.assertEqual(deliveries, [])
        self.assertEqual(self.service.status()["baseline"]["provider"], "wer_api")

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
        self.assertEqual(fake.delivery_calls, [])
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

    async def test_multiple_new_files_each_use_their_own_share_link(self) -> None:
        direct = RecordingDirectResolver()
        live = LiveDirectoryResolver([resolved("A.zip", "1")], direct)
        self.service.directory_resolver = live
        self.service._deliver = lambda _payload: {"ok": True, "uploaded": True}
        await self.service.check_once()

        added_b = resolved("B.zip", "1")
        added_c = resolved("C.zip", "1")
        live.files = [resolved("A.zip", "1"), added_b, added_c]
        result = await self.service.check_once()

        self.assertEqual(result["uploaded_count"], 2)
        self.assertEqual(direct.calls, [added_b.file.share_link, added_c.file.share_link])

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

    async def test_direct_resolver_failure_keeps_pending_and_skips_callback(self) -> None:
        direct = RecordingDirectResolver()
        live = LiveDirectoryResolver([resolved("A.zip", "1")], direct)
        self.service.directory_resolver = live
        callbacks: list[dict] = []
        self.service._deliver = lambda payload: callbacks.append(payload) or {"ok": True, "uploaded": True}
        await self.service.check_once()
        before = self.service.status()["baseline"]["signature"]

        added = resolved("B.zip", "1")
        live.files = [resolved("A.zip", "1"), added]
        direct.error = TargetFileWatchError("direct resolver failed")
        with self.assertRaisesRegex(TargetFileWatchError, "direct resolver failed"):
            await self.service.check_once()

        status = self.service.status()
        self.assertEqual(status["baseline"]["signature"], before)
        self.assertEqual(len(status["pending"]["events"]), 1)
        self.assertEqual(callbacks, [])
        self.assertEqual(direct.calls, [added.file.share_link])

    def test_delivery_resolution_uses_concrete_share_link_not_folder_url(self) -> None:
        direct = RecordingDirectResolver()
        item = resolved("U13LKcQg2.7z", "1")
        live = LiveDirectoryResolver([item], direct)

        delivery = live.resolve_for_delivery(SOURCE_URL, item.key, item.file.fingerprint)

        self.assertEqual(direct.calls, [item.file.share_link])
        self.assertNotIn(SOURCE_URL, direct.calls)
        self.assertTrue(delivery.direct_url.startswith("https://download.example.invalid/"))

    def test_source_folder_url_is_never_accepted_as_direct_url(self) -> None:
        direct = RecordingDirectResolver()
        direct.return_url = SOURCE_URL
        item = resolved("U13LKcQg2.7z", "1")
        live = LiveDirectoryResolver([item], direct)

        with self.assertRaisesRegex(TargetFileWatchError, "拒绝作为下载地址"):
            live.resolve_for_delivery(SOURCE_URL, item.key, item.file.fingerprint)

    def test_target_file_directory_strategy_ignores_legacy_provider_order(self) -> None:
        native_file = FileEntry(id="iNative", name="Native.zip", link="https://wwbvf.lanzn.com/iNative")
        fallback_file = FileEntry(id="iFallback", name="Fallback.zip", link="https://wwbvf.lanzn.com/iFallback")
        native = FakeSnapshotProvider("lanzou_web", [native_file])
        fallback = FakeSnapshotProvider("wer_api", [fallback_file])
        config = TargetFileWatchProviderConfig(wer_api_key="test-key-not-secret")
        resolver = DirectoryLanzouResolver(
            provider_config_loader=lambda: config,
            native_provider=native,
            fallback_provider=fallback,
        )

        snapshot = resolver.resolve_snapshot(SOURCE_URL)

        self.assertEqual(snapshot.provider, "lanzou_web")
        self.assertEqual(native.calls, [SOURCE_URL])
        self.assertEqual(fallback.calls, [])

    def test_direct_provider_receives_single_file_share_link(self) -> None:
        share_link = "https://wwbvf.lanzn.com/iU13LKcQg2"
        direct_url = "https://download.example.invalid/U13LKcQg2.7z?sign=fresh"
        provider = FakeSnapshotProvider(
            "wer_api",
            [
                FileEntry(
                    id="U13LKcQg2",
                    name="U13LKcQg2.7z",
                    link=share_link,
                    raw={"url": share_link, "downurl": direct_url},
                )
            ],
        )
        resolver = TargetFileDirectResolver(
            provider_config_loader=lambda: TargetFileWatchProviderConfig(wer_api_key="test-key-not-secret"),
            provider=provider,
        )

        result = resolver.resolve(share_link)

        self.assertEqual(provider.calls, [share_link])
        self.assertEqual(result, direct_url)

    def test_direct_provider_failure_never_logs_secret(self) -> None:
        secret = "DO-NOT-LEAK-THIS-SECRET"
        provider = FakeSnapshotProvider("wer_api", [], fail=RuntimeError(f"boom {secret}"))
        resolver = TargetFileDirectResolver(
            provider_config_loader=lambda: TargetFileWatchProviderConfig(wer_api_key=secret),
            provider=provider,
        )

        with self.assertLogs("LOLDataSystem.TargetFileWatch", level="WARNING") as captured:
            with self.assertRaises(TargetFileWatchError) as raised:
                resolver.resolve("https://wwbvf.lanzn.com/iSecretTest")

        combined = "\n".join(captured.output) + "\n" + str(raised.exception)
        self.assertNotIn(secret, combined)


if __name__ == "__main__":
    unittest.main()
