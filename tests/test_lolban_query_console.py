from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from lanzou_update_push_api_server.lolban_console import (
    _merge_masked,
    _provider_identity,
    render_lolban_console_page,
)
from lanzou_update_push_api_server.ui_theme import apply_ios_glass_theme
from routers.query_admin import _apply_reload_environment, _redact


class LolbanQueryConsoleTests(unittest.TestCase):
    def test_runtime_redaction_hides_literal_credentials(self):
        value = {
            "request": {
                "url": "https://example.test/query",
                "headers": {
                    "Authorization": "Bearer real-secret",
                    "X-Api-Key": "$secret:LOLBAN_KEY",
                },
                "query": {"token": "literal-token", "qq": "$qq"},
            }
        }
        redacted = _redact(value)
        self.assertEqual(redacted["request"]["headers"]["Authorization"], "***")
        self.assertEqual(redacted["request"]["headers"]["X-Api-Key"], "$secret:LOLBAN_KEY")
        self.assertEqual(redacted["request"]["query"]["token"], "***")
        self.assertEqual(redacted["request"]["query"]["qq"], "$qq")

    def test_masked_round_trip_preserves_existing_secret(self):
        previous = {"headers": {"Authorization": "Bearer old"}, "query": {"qq": "$qq"}}
        submitted = {"headers": {"Authorization": "***"}, "query": {"qq": "$qq"}}
        merged = _merge_masked(submitted, previous)
        self.assertEqual(merged["headers"]["Authorization"], "Bearer old")
        self.assertEqual(merged["query"]["qq"], "$qq")

    def test_reload_environment_is_strictly_allowlisted(self):
        with patch.dict(os.environ, {}, clear=False):
            changed = _apply_reload_environment(
                {"environment": {"LOL_BAN_TIMEOUT": "12", "LOL_BAN_SNAPSHOT_ENABLED": "1"}}
            )
            self.assertEqual(changed, ["LOL_BAN_TIMEOUT", "LOL_BAN_SNAPSHOT_ENABLED"])
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "12")
        with self.assertRaises(HTTPException):
            _apply_reload_environment({"environment": {"PATH": "unsafe"}})

    def test_provider_identity_exposes_operational_fields_only(self):
        identity = _provider_identity(
            {
                "id": "primary",
                "enabled": True,
                "request": {
                    "method": "post",
                    "url": "https://example.test/query",
                    "headers": {"Authorization": "secret"},
                },
            },
            1,
        )
        self.assertEqual(
            identity,
            {
                "order": 1,
                "id": "primary",
                "enabled": True,
                "method": "POST",
                "url": "https://example.test/query",
            },
        )

    def test_dedicated_page_contains_required_diagnostics(self):
        page = render_lolban_console_page()
        self.assertIn("封号查询配置与实时诊断", page)
        self.assertIn("Provider 直连", page)
        self.assertIn("5001 正式链路", page)
        self.assertIn("/admin/query-console/lolban/save", page)
        self.assertIn("/admin/query-console/lolban/test", page)

    def test_root_dashboard_theme_injects_lolban_entry(self):
        page = apply_ios_glass_theme(
            '<!doctype html><html><head></head><body><div class="actions"></div></body></html>'
        )
        self.assertIn("data-query-console-lolban", page)
        self.assertIn("/query-console/lolban", page)
        self.assertIn("封号查询配置", page)


if __name__ == "__main__":
    unittest.main()
