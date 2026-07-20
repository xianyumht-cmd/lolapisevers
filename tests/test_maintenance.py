import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lanzou_update_push_api_server import maintenance


class MaintenanceTests(unittest.TestCase):
    def test_main_config_backup_can_be_listed_and_rolled_back(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_path = root / "app_env.local.ps1"
            lanzou_path = root / "config.json"
            main_path.write_text('$env:APP_PORT = "6000"\n', encoding="utf-8")
            backup = root / "app_env.local.ps1.bak.20260720T000000000000Z"
            backup.write_text('$env:APP_PORT = "5001"\n', encoding="utf-8")
            lanzou_path.write_text("{}", encoding="utf-8")

            with patch.object(maintenance, "APP_ENV_PATH", main_path), patch.dict(
                os.environ,
                {"LANZOU_MONITOR_CONFIG": str(lanzou_path)},
                clear=False,
            ):
                listed = maintenance.list_config_backups()
                result = maintenance.rollback_config("main", backup.name)

            self.assertEqual(listed["backups"][0]["name"], backup.name)
            self.assertIn('$env:APP_PORT = "5001"', main_path.read_text(encoding="utf-8"))
            self.assertTrue(Path(result["safety_backup"]).exists())
            self.assertTrue(result["restart_required"])

    def test_lanzou_rollback_validates_json_and_returns_loaded_config(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_path = root / "app_env.local.ps1"
            lanzou_path = root / "config.json"
            state_path = root / "state.json"
            main_path.write_text("", encoding="utf-8")
            lanzou_path.write_text(
                json.dumps({"port": 6178, "state_path": str(state_path)}),
                encoding="utf-8",
            )
            backup = root / "config.json.bak.20260720T000000000000Z"
            backup.write_text(
                json.dumps({"port": 7000, "state_path": str(state_path)}),
                encoding="utf-8",
            )

            with patch.object(maintenance, "APP_ENV_PATH", main_path), patch.dict(
                os.environ,
                {"LANZOU_MONITOR_CONFIG": str(lanzou_path)},
                clear=False,
            ):
                result = maintenance.rollback_config("lanzou", backup.name)

            self.assertEqual(result["config"].port, 7000)
            self.assertFalse(result["restart_required"])
            self.assertEqual(json.loads(lanzou_path.read_text(encoding="utf-8"))["port"], 7000)

    def test_audit_log_does_not_require_existing_directory(self):
        with TemporaryDirectory() as temp_dir:
            audit_path = Path(temp_dir) / "logs" / "admin_audit.jsonl"
            with patch.object(maintenance, "AUDIT_PATH", audit_path), patch.object(
                maintenance,
                "LOGS_DIR",
                audit_path.parent,
            ):
                maintenance.append_audit(
                    action="config_saved",
                    ok=True,
                    client="127.0.0.1",
                    method="POST",
                    path="/admin/main-config",
                    detail={"fields": ["APP_PORT"]},
                )
                payload = maintenance.read_audit(10)

            self.assertEqual(payload["events"][0]["action"], "config_saved")
            self.assertNotIn("password", audit_path.read_text(encoding="utf-8").lower())

    def test_backup_name_cannot_escape_config_directory(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_path = root / "app_env.local.ps1"
            lanzou_path = root / "config.json"
            main_path.write_text("", encoding="utf-8")
            lanzou_path.write_text("{}", encoding="utf-8")

            with patch.object(maintenance, "APP_ENV_PATH", main_path), patch.dict(
                os.environ,
                {"LANZOU_MONITOR_CONFIG": str(lanzou_path)},
                clear=False,
            ):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    maintenance.rollback_config("main", "../app_env.local.ps1.bak.fake")


if __name__ == "__main__":
    unittest.main()
