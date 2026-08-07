from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TargetFileWatchImportSafetyTest(unittest.TestCase):
    def test_runtime_import_does_not_create_unconfigured_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "target-file-watch.json"
            state_path = root / "target-file-watch-state.json"
            env = os.environ.copy()
            env["TARGET_FILE_WATCH_CONFIG_PATH"] = str(config_path)
            env["TARGET_FILE_WATCH_STATE_PATH"] = str(state_path)

            completed = subprocess.run(
                [sys.executable, "-c", "import services.target_file_watch_runtime"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(config_path.exists())
            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
