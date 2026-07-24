from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server import config_facade, management


class MainConfigFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.local_path = root / "app_env.local.ps1"
        self.example_path = root / "app_env.example.ps1"
        self.local_path.write_text('$env:APP_PORT = "5001"\n', encoding="utf-8")
        self.example_path.write_text(
            '\n'.join(
                [
                    '$env:APP_HOST = "0.0.0.0"',
                    '$env:APP_PORT = "5001"',
                    '$env:PYTHONIOENCODING = "utf-8"',
                    '$env:CACHE_SECONDS = "300"',
                    '$env:SHARD_CACHE_SECONDS = "600"',
                    '$env:ARAM_AUGMENT_CACHE_SECONDS = "1800"',
                    '$env:MYSQL_HOST = "127.0.0.1"',
                    '$env:MYSQL_PORT = "3306"',
                    '$env:MYSQL_USER = "root"',
                    '$env:MYSQL_PASSWORD = "CHANGE_ME"',
                    '$env:MYSQL_DATABASE = "lol_data"',
                    '$env:SO1_USERNAME = "CHANGE_ME"',
                    '$env:SO1_PASSWORD = "CHANGE_ME"',
                    '$env:SO1_HEADLESS = "1"',
                    '$env:SO1_TIMEOUT_MS = "20000"',
                    '$env:SO1_MAX_CONCURRENT_PAGES = "2"',
                    '$env:PLAYWRIGHT_BROWSERS_PATH = "C:\\ms-playwright"',
                    '$env:KEEPALIVE_BASE_URL = "http://127.0.0.1:5001"',
                    '$env:KEEPALIVE_TEST_NAME = "testplayer#12345"',
                    '$env:KEEPALIVE_TEST_REGION = "HN1"',
                    '$env:SHARD_DATA_URL = "https://example.com/default-shards.json"',
                    '$env:SHARD_HERO_URL = "https://example.com/default-heroes.json"',
                    '$env:WEBUI_ADMIN_TOKEN = ""',
                ]
            ) + '\n',
            encoding="utf-8",
        )
        self.path_patches = [
            patch.object(management, "APP_ENV_PATH", self.local_path),
            patch.object(management, "APP_ENV_EXAMPLE_PATH", self.example_path),
        ]
        for item in self.path_patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.path_patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_read_fills_fields_missing_from_old_local_file(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = config_facade.read_main_config()

        fields = {item["key"]: item for item in result["fields"]}
        self.assertEqual(fields["APP_HOST"]["value"], "0.0.0.0")
        self.assertEqual(fields["APP_PORT"]["value"], "5001")
        self.assertEqual(
            fields["SHARD_DATA_URL"]["value"],
            "https://example.com/default-shards.json",
        )
        self.assertEqual(
            fields["SHARD_HERO_URL"]["value"],
            "https://example.com/default-heroes.json",
        )
        self.assertTrue(fields["APP_HOST"]["inherited_from_example"])
        self.assertNotIn("inherited_from_example", fields["APP_PORT"])

    def test_save_reuses_required_default_instead_of_failing_on_blank_host(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = config_facade.update_main_config(
                {
                    "APP_HOST": "",
                    "APP_PORT": "5001",
                    "SHARD_DATA_URL": "https://example.com/new-shards.json",
                    "SHARD_HERO_URL": "https://example.com/new-heroes.json",
                }
            )

        saved = self.local_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn('$env:APP_HOST = "0.0.0.0"', saved)
        self.assertIn('$env:SHARD_DATA_URL = "https://example.com/new-shards.json"', saved)
        self.assertIn('$env:SHARD_HERO_URL = "https://example.com/new-heroes.json"', saved)

    def test_invalid_integer_still_raises_validation_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "APP_PORT"):
                config_facade.update_main_config({"APP_PORT": "not-a-number"})


if __name__ == "__main__":
    unittest.main()
