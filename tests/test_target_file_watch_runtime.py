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


if __name__ == "__main__":
    unittest.main()
