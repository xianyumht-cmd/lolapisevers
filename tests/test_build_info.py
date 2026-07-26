import json
import tempfile
import unittest
from pathlib import Path

from core.build_info import load_build_info


class BuildInfoTests(unittest.TestCase):
    def test_missing_metadata_is_explicitly_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = load_build_info(
                environ={},
                path=Path(temp_dir) / "missing.json",
            )

        self.assertEqual(payload["source"], "unknown")
        self.assertEqual(payload["commit_sha"], "unknown")
        self.assertFalse(payload["commit_complete"])
        self.assertEqual(payload["service"], "lolapisevers")

    def test_build_file_accepts_only_full_commit_sha(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build-info.json"
            path.write_text(
                json.dumps(
                    {
                        "release": "2026.07.26",
                        "commit_sha": "ABCDEF1" * 5 + "ABCDE",
                        "built_at": "2026-07-26T08:00:00Z",
                        "contract_version": "2",
                        "config_schema_version": "1",
                        "dirty": False,
                        "source_manifest": {
                            "algorithm": "sha256",
                            "aggregate_sha256": "A" * 64,
                            "file_count": 42,
                            "files": [{"path": "app.py", "sha256": "B" * 64}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = load_build_info(environ={}, path=path)

        self.assertEqual(payload["source"], "file")
        self.assertEqual(payload["commit_sha"], ("abcdef1" * 5 + "abcde"))
        self.assertTrue(payload["commit_complete"])
        self.assertEqual(payload["release"], "2026.07.26")
        self.assertFalse(payload["dirty"])
        self.assertEqual(
            payload["source_manifest"],
            {
                "algorithm": "sha256",
                "aggregate_sha256": "a" * 64,
                "file_count": 42,
            },
        )

    def test_short_commit_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build-info.json"
            path.write_text('{"commit_sha":"9cef542"}', encoding="utf-8")
            payload = load_build_info(environ={}, path=path)

        self.assertEqual(payload["commit_sha"], "unknown")
        self.assertFalse(payload["commit_complete"])

    def test_dirty_build_is_not_reported_as_commit_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build-info.json"
            path.write_text(
                json.dumps(
                    {
                        "commit_sha": "1" * 40,
                        "dirty": True,
                    }
                ),
                encoding="utf-8",
            )

            payload = load_build_info(environ={}, path=path)

        self.assertTrue(payload["dirty"])
        self.assertFalse(payload["commit_complete"])

    def test_environment_overrides_build_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build-info.json"
            path.write_text(
                json.dumps(
                    {
                        "commit_sha": "1" * 40,
                        "release": "from-file",
                    }
                ),
                encoding="utf-8",
            )
            payload = load_build_info(
                environ={
                    "BUILD_COMMIT_SHA": "2" * 40,
                    "BUILD_RELEASE": "from-env",
                    "BUILD_TIME": "2026-07-26T09:00:00Z",
                },
                path=path,
            )

        self.assertEqual(payload["source"], "environment")
        self.assertEqual(payload["commit_sha"], "2" * 40)
        self.assertEqual(payload["release"], "from-env")
        self.assertEqual(payload["built_at"], "2026-07-26T09:00:00Z")


if __name__ == "__main__":
    unittest.main()
