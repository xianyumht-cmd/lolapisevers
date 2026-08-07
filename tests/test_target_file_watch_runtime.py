from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.target_file_watch_runtime import SafeTargetFileWatchService
from services.target_file_watch_service import TargetFileWatchError


class SafeTargetFileWatchRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_state_blocks_checks_until_explicit_rebaseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "target-file-watch.json"
            state_path = root / "target-file-watch-state.json"
            corrupt_text = '{"version":1,"baseline":'
            state_path.write_text(corrupt_text, encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "TARGET_FILE_WATCH_CONFIG_PATH": str(config_path),
                    "TARGET_FILE_WATCH_STATE_PATH": str(state_path),
                },
                clear=False,
            ):
                service = SafeTargetFileWatchService()
                status = service.status()
                self.assertFalse(status["ok"])
                self.assertFalse(status["state_healthy"])
                self.assertEqual(status["state_error_code"], "target_file_watch_state_corrupt")

                with self.assertRaisesRegex(TargetFileWatchError, "state_unavailable"):
                    await service.check_once()

                self.assertEqual(state_path.read_text(encoding="utf-8"), corrupt_text)
                recovered = service.rebaseline()
                self.assertTrue(recovered["ok"])
                self.assertTrue(recovered["state_healthy"])
                self.assertTrue(recovered["state_quarantine_file"].startswith("target-file-watch-state.json.corrupt-"))

                quarantine = root / recovered["state_quarantine_file"]
                self.assertTrue(quarantine.is_file())
                self.assertEqual(quarantine.read_text(encoding="utf-8"), corrupt_text)
                self.assertTrue(state_path.is_file())
                self.assertIn('"version": 1', state_path.read_text(encoding="utf-8"))

    async def test_disabled_to_enabled_transition_discards_old_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "target-file-watch.json"
            state_path = root / "target-file-watch-state.json"
            source_url = "https://abc.lanzou.com/iTEST"
            callback_url = "http://192.168.3.89:6108/api/target-file-push/event"
            callback_token = "0123456789abcdef0123456789abcdef"

            with patch.dict(
                os.environ,
                {
                    "TARGET_FILE_WATCH_CONFIG_PATH": str(config_path),
                    "TARGET_FILE_WATCH_STATE_PATH": str(state_path),
                },
                clear=False,
            ):
                service = SafeTargetFileWatchService()
                service.save_config(
                    {
                        "enabled": False,
                        "source_url": source_url,
                        "callback_url": callback_url,
                    }
                )
                service._state["baseline"] = {
                    "fingerprint": "sha256:old-before-disabled-period",
                    "name": "old.zip",
                }
                service._save_state()
                self.assertIsNotNone(service.status()["baseline"])

                enabled = service.save_config(
                    {
                        "enabled": True,
                        "source_url": source_url,
                        "callback_url": callback_url,
                        "callback_token": callback_token,
                        "check_interval_seconds": 300,
                    }
                )
                self.assertTrue(enabled["config"]["enabled"])
                self.assertIsNone(enabled["baseline"])
                self.assertIsNone(enabled["pending"])


if __name__ == "__main__":
    unittest.main()
