from __future__ import annotations

import unittest
from unittest.mock import patch

from lanzou_update_push_api_server.config import AppConfig
from lanzou_update_push_api_server.providers import FileEntry, ShareSnapshot
from services.target_file_watch_directory import (
    DirectoryLanzouResolver,
    DirectoryResolvedFile,
    DirectorySnapshot,
    TARGET_FILE_DIRECT_WER_ENDPOINT,
)
from services.target_file_watch_service import ResolvedTargetFile


SOURCE_URL = "https://wwbvf.lanzn.com/b016kzvvmd"
FOLDER_WER_ENDPOINT = "https://api2.wer.plus/api/lanzpro"


class CapturingProviderChain:
    seen_config: AppConfig | None = None

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        type(self).seen_config = config

    def fetch(self, watcher) -> ShareSnapshot:
        return ShareSnapshot(
            watcher_id=watcher.id,
            title=watcher.title,
            url=watcher.url,
            provider="wer_api",
            fetched_at="2026-08-16T00:00:00+00:00",
            files=[
                FileEntry(
                    id="current-id",
                    name="Current.zip",
                    size="10 MB",
                    link="https://wwbvf.lanzn.com/iCURRENT",
                )
            ],
        )


class FakeWerApiProvider:
    seen_endpoint = ""
    seen_url = ""

    def fetch(self, watcher, config: AppConfig) -> ShareSnapshot:
        type(self).seen_endpoint = config.wer_api_endpoint
        type(self).seen_url = watcher.url
        direct_url = "https://download.example.invalid/current.zip?sign=fresh"
        return ShareSnapshot(
            watcher_id=watcher.id,
            title=watcher.title,
            url=watcher.url,
            provider="wer_api",
            fetched_at="2026-08-16T00:00:00+00:00",
            files=[
                FileEntry(
                    id="current-id",
                    name="Current.zip",
                    size="10 MB",
                    link=direct_url,
                    raw={"downurl": direct_url},
                )
            ],
        )


class TargetFileWatchProviderEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        CapturingProviderChain.seen_config = None
        FakeWerApiProvider.seen_endpoint = ""
        FakeWerApiProvider.seen_url = ""

    def test_folder_snapshot_keeps_configured_lanzpro_fallback(self) -> None:
        provider_config = AppConfig(
            provider_order=["lanzou_web", "wer_api"],
            wer_api_endpoint=FOLDER_WER_ENDPOINT,
            wer_api_key="configured-key",
        )
        resolver = DirectoryLanzouResolver()

        with (
            patch(
                "services.target_file_watch_directory.load_lanzou_provider_config",
                return_value=provider_config,
            ),
            patch(
                "services.target_file_watch_directory.ProviderChain",
                CapturingProviderChain,
            ),
        ):
            snapshot = resolver.resolve_snapshot(SOURCE_URL)

        self.assertIs(CapturingProviderChain.seen_config, provider_config)
        self.assertEqual(CapturingProviderChain.seen_config.wer_api_endpoint, FOLDER_WER_ENDPOINT)
        self.assertEqual(snapshot.provider, "wer_api")
        self.assertEqual(snapshot.files[0].file.name, "Current.zip")

    def test_concrete_file_delivery_still_forces_lanz_endpoint(self) -> None:
        provider_config = AppConfig(
            provider_order=["lanzou_web", "wer_api"],
            wer_api_endpoint=FOLDER_WER_ENDPOINT,
            wer_api_key="configured-key",
        )
        current = ResolvedTargetFile(
            fingerprint="sha256:current",
            stable_id="current-id",
            name="Current.zip",
            size="10 MB",
            modified_time="2026-08-16",
            share_link="https://wwbvf.lanzn.com/iCURRENT",
            provider="lanzou_web",
        )
        item = DirectoryResolvedFile(key="name:current.zip", file=current)
        snapshot = DirectorySnapshot(provider="lanzou_web", files=(item,))
        resolver = DirectoryLanzouResolver()

        with (
            patch.object(resolver, "resolve_snapshot", return_value=snapshot),
            patch(
                "services.target_file_watch_directory.load_lanzou_provider_config",
                return_value=provider_config,
            ),
            patch(
                "services.target_file_watch_directory.WerApiProvider",
                FakeWerApiProvider,
            ),
        ):
            delivered = resolver.resolve_for_delivery(
                SOURCE_URL,
                item.key,
                current.fingerprint,
            )

        self.assertEqual(FakeWerApiProvider.seen_endpoint, TARGET_FILE_DIRECT_WER_ENDPOINT)
        self.assertEqual(FakeWerApiProvider.seen_url, current.share_link)
        self.assertEqual(
            delivered.direct_url,
            "https://download.example.invalid/current.zip?sign=fresh",
        )


if __name__ == "__main__":
    unittest.main()
