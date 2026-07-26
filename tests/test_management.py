import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lanzou_update_push_api_server import management


class ManagementTests(unittest.TestCase):
    def test_powershell_value_round_trip_escapes_variable_expansion(self):
        value = '{"url":"https://example.test/query?literal=$env:SHOULD_NOT_EXPAND","note":"`quoted`"}'
        formatted = management._format_ps_value(value)

        self.assertIn("`$env:SHOULD_NOT_EXPAND", formatted)
        self.assertEqual(management._parse_ps_value(formatted), value)

    def test_main_config_save_preserves_blank_secret_and_creates_backup(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_path = root / "app_env.local.ps1"
            example_path = root / "app_env.example.ps1"
            local_path.write_text(
                '$env:APP_PORT = "5001"\n$env:MYSQL_PASSWORD = "existing-secret"\n',
                encoding="utf-8",
            )
            example_path.write_text('$env:APP_PORT = "5001"\n', encoding="utf-8")

            with patch.object(management, "APP_ENV_PATH", local_path), patch.object(
                management, "APP_ENV_EXAMPLE_PATH", example_path
            ):
                result = management.update_main_config({"APP_PORT": 6001, "MYSQL_PASSWORD": ""})
                payload = management.read_main_config()

            saved = local_path.read_text(encoding="utf-8")
            self.assertIn('$env:APP_PORT = "6001"', saved)
            self.assertIn('$env:MYSQL_PASSWORD = "existing-secret"', saved)
            self.assertTrue(Path(result["backup_path"]).exists())
            secret = next(item for item in payload["fields"] if item["key"] == "MYSQL_PASSWORD")
            self.assertTrue(secret["configured"])
            self.assertEqual(secret["value"], "")

    def test_lanzou_config_supports_all_global_fields_watchers_and_targets(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(
                json.dumps(
                    {
                        "host": "127.0.0.1",
                        "port": 6178,
                        "state_path": str(state_path),
                        "watchers": [],
                        "notify_targets": [],
                    }
                ),
                encoding="utf-8",
            )
            patch_payload = {
                "host": "0.0.0.0",
                "port": 6180,
                "scan_interval_seconds": 60,
                "scan_batch_size": 2,
                "scan_batch_pause_seconds": 5,
                "scan_on_start": False,
                "provider_order": ["wer_api", "lanzou_web"],
                "wer_api_endpoint": "https://example.test/api",
                "wer_api_method": "POST",
                "wer_api_url_param": "share_url",
                "wer_api_password_param": "share_pwd",
                "wer_api_key": "demo-key",
                "notification_template": "{title} changed",
                "state_path": str(state_path),
                "watchers": [
                    {
                        "id": "demo",
                        "title": "Demo",
                        "url": "https://example.test/share",
                        "password": "1234",
                        "enabled": True,
                        "max_pages": 9,
                    }
                ],
                "notify_targets": [
                    {
                        "name": "target",
                        "enabled": True,
                        "url": "http://127.0.0.1:6108/event",
                        "timeout_seconds": 4,
                        "headers": {"x-token": "secret"},
                    }
                ],
            }

            with patch.dict(os.environ, {"LANZOU_MONITOR_CONFIG": str(config_path)}, clear=False):
                config, backup_path = management.update_lanzou_config(patch_payload)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config.host, "0.0.0.0")
            self.assertEqual(config.port, 6180)
            self.assertEqual(saved["watchers"][0]["id"], "demo")
            self.assertEqual(saved["notify_targets"][0]["headers"]["x-token"], "secret")
            self.assertTrue(Path(backup_path).exists())

    def test_log_reader_returns_tail_and_supports_filtering(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "demo.log"
            path.write_text("one\ntwo error\nthree\nfour error\n", encoding="utf-8")

            with patch.object(management, "LOG_FILES", {"demo": path}):
                tail = management.read_log("demo", lines=3)
                filtered = management.read_log("demo", lines=10, search="error")

            self.assertEqual(tail["content"], "two error\nthree\nfour error\n")
            self.assertEqual(filtered["content"], "two error\nfour error\n")

    def test_api_invoker_returns_json_metadata(self):
        class FakeResponse:
            ok = True
            status_code = 200
            headers = {"content-type": "application/json"}
            text = '{"status":"ok"}'
            content = text.encode("utf-8")

            @staticmethod
            def json():
                return {"status": "ok"}

        with patch.object(management.requests, "request", return_value=FakeResponse()) as request_mock:
            result = management.invoke_local_api(
                {
                    "service": "main",
                    "method": "GET",
                    "path": "/health",
                    "query": {"verbose": "1"},
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["json"]["status"], "ok")
        request_mock.assert_called_once()
        self.assertEqual(request_mock.call_args.args[1], "http://127.0.0.1:5001/health")


if __name__ == "__main__":
    unittest.main()
