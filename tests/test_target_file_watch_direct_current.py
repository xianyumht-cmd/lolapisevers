from __future__ import annotations

import unittest
from types import SimpleNamespace

from lanzou_update_push_api_server.providers import FileEntry
from services.target_file_watch_directory import (
    DirectoryResolvedFile,
    DirectorySnapshot,
    TargetFileDirectResolver,
    TargetFileDirectoryResolver,
    TargetFileWatchProviderConfig,
)
from services.target_file_watch_service import ResolvedTargetFile, TargetFileWatchError


SOURCE_URL = "https://wwbvf.lanzn.com/b016kzvvmd"
SHARE_LINK = "https://wwbvf.lanzn.com/iConcreteFile"
DIRECT_URL = "https://download.example.invalid/concrete.bin"


class RecordingProvider:
    name = "wer_api"

    def __init__(self, *, direct_url: str = DIRECT_URL) -> None:
        self.calls: list[str] = []
        self.direct_url = direct_url

    def fetch(self, watcher, _config):
        self.calls.append(watcher.url)
        return SimpleNamespace(
            provider=self.name,
            files=[
                FileEntry(
                    id="file-1",
                    name="Client.7z",
                    link=SHARE_LINK,
                    raw={"downurl": self.direct_url},
                )
            ],
        )


class RecordingDirectResolver:
    def __init__(self, result: str = DIRECT_URL) -> None:
        self.calls: list[str] = []
        self.result = result

    def resolve(self, share_link: str) -> str:
        self.calls.append(share_link)
        return self.result


class SnapshotResolver(TargetFileDirectoryResolver):
    def __init__(self, direct_resolver: RecordingDirectResolver) -> None:
        super().__init__(direct_resolver=direct_resolver)
        self.item = DirectoryResolvedFile(
            key="name:client.7z",
            file=ResolvedTargetFile(
                fingerprint="sha256:current-file",
                stable_id="file-1",
                name="Client.7z",
                size="1 MB",
                modified_time="2026-08-08",
                share_link=SHARE_LINK,
                provider="lanzou_web",
            ),
            provider_fingerprint="sha256:provider-current",
        )

    def resolve_snapshot(self, _source_url: str) -> DirectorySnapshot:
        return DirectorySnapshot(provider="lanzou_web", files=(self.item,))


class TargetFileDirectCurrentTests(unittest.TestCase):
    def test_direct_provider_receives_concrete_file_share_link(self) -> None:
        provider = RecordingProvider()
        resolver = TargetFileDirectResolver(
            provider_config_loader=lambda: TargetFileWatchProviderConfig(wer_api_key="test-key"),
            provider=provider,
        )

        result = resolver.resolve(SHARE_LINK)

        self.assertEqual(result, DIRECT_URL)
        self.assertEqual(provider.calls, [SHARE_LINK])
        self.assertNotIn(SOURCE_URL, provider.calls)

    def test_delivery_resolution_uses_metadata_share_link_not_folder_url(self) -> None:
        direct = RecordingDirectResolver()
        resolver = SnapshotResolver(direct)

        delivery = resolver.resolve_for_delivery(
            SOURCE_URL,
            resolver.item.key,
            resolver.item.file.fingerprint,
        )

        self.assertEqual(direct.calls, [SHARE_LINK])
        self.assertEqual(delivery.direct_url, DIRECT_URL)

    def test_folder_url_is_rejected_as_direct_result(self) -> None:
        direct = RecordingDirectResolver(result=SOURCE_URL)
        resolver = SnapshotResolver(direct)

        with self.assertRaisesRegex(TargetFileWatchError, "拒绝作为下载地址"):
            resolver.resolve_for_delivery(
                SOURCE_URL,
                resolver.item.key,
                resolver.item.file.fingerprint,
            )

    def test_share_link_itself_is_rejected_as_direct_result(self) -> None:
        direct = RecordingDirectResolver(result=SHARE_LINK)
        resolver = SnapshotResolver(direct)

        with self.assertRaisesRegex(TargetFileWatchError, "拒绝作为下载地址"):
            resolver.resolve_for_delivery(
                SOURCE_URL,
                resolver.item.key,
                resolver.item.file.fingerprint,
            )


if __name__ == "__main__":
    unittest.main()
