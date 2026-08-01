import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server import management
from lanzou_update_push_api_server.parser_center_admin import (
    _redact_config,
    list_parser_backups,
    read_parser_center,
    rollback_parser_center,
    save_parser_center,
    save_parser_secret,
)


def config(*, enabled=False, template="状态：{status}"):
    return {
        "schema": "lapi-parser-center.v1",
        "features": {
            "lolban": {
                "operation": "query",
                "providers": [
                    {
                        "id": "lolban-primary",
                        "enabled": enabled,
                        "request": {
                            "method": "GET",
                            "url": "https://example.test/query",
                            "query": {
                                "qq": "$qq",
                                "token": "$secret:LOLMAP_API_TOKEN",
                            },
                        },
                        "parser": {
                            "success": {"path": "code", "op": "eq", "value": 200},
                            "fields": {"status": {"paths": ["data.status"]}},
                            "templates": {"default": template},
                        },
                    }
                ],
            }
        },
    }


class ParserCenterAdminTests(unittest.TestCase):
    def test_config_round_trip_preserves_secret_reference(self):
        safe = _redact_config(
            {
                "query": {
                    "token": "$secret:LOLMAP_API_TOKEN",
                    "api_key": "literal-must-not-return",
                }
            }
        )

        self.assertEqual(safe["query"]["token"], "$secret:LOLMAP_API_TOKEN")
        self.assertEqual(safe["query"]["api_key"], "***")
        self.assertNotIn("literal-must-not-return", str(safe))

    def test_read_and_save_preserve_secret_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "interface-parser-center.json"
            with patch.dict(os.environ, {"INTERFACE_PARSER_CENTER_PATH": str(path)}, clear=False):
                saved = save_parser_center({"config": config()})
                loaded = read_parser_center()

        self.assertEqual(
            saved["config"]["features"]["lolban"]["providers"][0]["request"]["query"]["token"],
            "$secret:LOLMAP_API_TOKEN",
        )
        self.assertEqual(
            loaded["config"]["features"]["lolban"]["providers"][0]["request"]["query"]["token"],
            "$secret:LOLMAP_API_TOKEN",
        )

    def test_secret_write_does_not_return_value_and_activates_test_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_path = root / "app_env.local.ps1"
            example_path = root / "app_env.example.ps1"
            local_path.write_text('$env:APP_PORT = "5001"\n', encoding="utf-8")
            example_path.write_text('$env:APP_PORT = "5001"\n', encoding="utf-8")
            field_existed = "LOLMAP_API_TOKEN" in management._FIELD_BY_KEY
            previous_field = management._FIELD_BY_KEY.get("LOLMAP_API_TOKEN")
            previous_length = len(management.MAIN_CONFIG_FIELDS)
            try:
                with patch(
                    "lanzou_update_push_api_server.parser_center_admin._load_effective_config",
                    return_value=(config(), root / "interface-parser-center.json", True),
                ), patch.object(management, "APP_ENV_PATH", local_path), patch.object(
                    management, "APP_ENV_EXAMPLE_PATH", example_path
                ), patch.dict(os.environ, {}, clear=False):
                    result = save_parser_secret(
                        {"name": "LOLMAP_API_TOKEN", "value": "top-secret-value"}
                    )
                    self.assertEqual(os.environ["LOLMAP_API_TOKEN"], "top-secret-value")
            finally:
                if not field_existed:
                    management._FIELD_BY_KEY.pop("LOLMAP_API_TOKEN", None)
                    del management.MAIN_CONFIG_FIELDS[previous_length:]
                elif previous_field is not None:
                    management._FIELD_BY_KEY["LOLMAP_API_TOKEN"] = previous_field

            written = local_path.read_text(encoding="utf-8-sig")

        self.assertIn("LOLMAP_API_TOKEN", written)
        self.assertIn("top-secret-value", written)
        self.assertNotIn("top-secret-value", json.dumps(result, ensure_ascii=False))
        self.assertTrue(result["configured"])
        self.assertTrue(result["test_available_immediately"])

    def test_backup_and_rollback_restore_previous_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "interface-parser-center.json"
            with patch.dict(os.environ, {"INTERFACE_PARSER_CENTER_PATH": str(path)}, clear=False):
                save_parser_center({"config": config(template="第一版：{status}")})
                save_parser_center({"config": config(enabled=True, template="第二版：{status}")})
                backups = list_parser_backups()["backups"]
                self.assertEqual(len(backups), 1)

                result = rollback_parser_center({"backup_name": backups[0]["name"]})
                restored = json.loads(path.read_text(encoding="utf-8"))

        provider = restored["features"]["lolban"]["providers"][0]
        self.assertFalse(provider["enabled"])
        self.assertEqual(provider["parser"]["templates"]["default"], "第一版：{status}")
        self.assertEqual(result["restored_from"], backups[0]["name"])
        self.assertTrue(result["restart_required"])


if __name__ == "__main__":
    unittest.main()
