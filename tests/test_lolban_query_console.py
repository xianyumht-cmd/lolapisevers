from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from fastapi import HTTPException

from lanzou_update_push_api_server import management
from lanzou_update_push_api_server.control_extensions import _register_sensitive_lolban_fields
from lanzou_update_push_api_server.lolban_console import (
    _merge_masked,
    _merge_masked_url,
    _merge_provider_list,
    _provider_identity,
    render_lolban_console_page,
    save_fourpng_token,
    save_provider_secret,
    test_lolban_console,
)
from lanzou_update_push_api_server.ui_theme import apply_ios_glass_theme
from routers.query_admin import (
    _apply_reload_environment,
    _provider_error_diagnostic,
    _redact,
)
from services.api_parser_center import ParserConfigError


class LolbanQueryConsoleTests(unittest.TestCase):
    def test_runtime_redaction_hides_literal_credentials(self):
        value = {
            "request": {
                "url": (
                    "https://user:pass@example.test/query?qq=$qq"
                    "&token=literal-token&api_key=$secret:LOLBAN_KEY"
                ),
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
        parts = urlsplit(redacted["request"]["url"])
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.assertEqual(parts.username, "***")
        self.assertEqual(query["token"], "***")
        self.assertEqual(query["api_key"], "$secret:LOLBAN_KEY")
        self.assertEqual(query["qq"], "$qq")
        self.assertNotIn("literal-token", redacted["request"]["url"])
        self.assertNotIn("pass", redacted["request"]["url"])

    def test_masked_round_trip_preserves_existing_secret(self):
        previous = {"headers": {"Authorization": "Bearer old"}, "query": {"qq": "$qq"}}
        submitted = {"headers": {"Authorization": "***"}, "query": {"qq": "$qq"}}
        merged = _merge_masked(submitted, previous)
        self.assertEqual(merged["headers"]["Authorization"], "Bearer old")
        self.assertEqual(merged["query"]["qq"], "$qq")

    def test_masked_url_round_trip_preserves_credentials(self):
        previous = "https://user:pass@example.test/query?qq=$qq&token=real-token"
        submitted = "https://***@example.test/query?qq=%24qq&token=%2A%2A%2A"
        merged = _merge_masked_url(submitted, previous)
        parts = urlsplit(merged)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.assertEqual(parts.username, "user")
        self.assertEqual(parts.password, "pass")
        self.assertEqual(query["token"], "real-token")
        self.assertEqual(query["qq"], "$qq")

    def test_provider_rename_preserves_masked_secret_by_position(self):
        previous = [
            {
                "id": "old-id",
                "request": {
                    "url": "https://example.test/query",
                    "headers": {"Authorization": "Bearer old"},
                },
            }
        ]
        submitted = [
            {
                "id": "new-id",
                "request": {
                    "url": "https://example.test/query",
                    "headers": {"Authorization": "***"},
                },
            }
        ]
        merged = _merge_provider_list(submitted, previous)
        self.assertEqual(merged[0]["id"], "new-id")
        self.assertEqual(merged[0]["request"]["headers"]["Authorization"], "Bearer old")

    def test_legacy_url_is_secret_in_generic_config_ui(self):
        _register_sensitive_lolban_fields()
        spec = management._FIELD_BY_KEY["LOL_BAN_UPSTREAM_URL"]
        self.assertEqual(spec["type"], "secret")
        self.assertIn("封号查询配置页", spec["label"])

    def test_reload_environment_is_strictly_allowlisted(self):
        with patch.dict(os.environ, {}, clear=False):
            changed = _apply_reload_environment(
                {"environment": {"LOL_BAN_TIMEOUT": "12", "LOL_BAN_SNAPSHOT_ENABLED": "1", "LOLMAP_API_TOKEN": "primary-secret", "LOL_BAN_4PNG_TOKEN": "backup-secret"}}
            )
            self.assertEqual(changed, ["LOL_BAN_TIMEOUT", "LOL_BAN_SNAPSHOT_ENABLED", "LOLMAP_API_TOKEN", "LOL_BAN_4PNG_TOKEN"])
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "12")
            self.assertEqual(os.environ["LOLMAP_API_TOKEN"], "primary-secret")
            self.assertEqual(os.environ["LOL_BAN_4PNG_TOKEN"], "backup-secret")
        with self.assertRaises(HTTPException):
            _apply_reload_environment({"environment": {"PATH": "unsafe"}})

    def test_provider_identity_exposes_operational_fields_only(self):
        identity = _provider_identity(
            {
                "id": "primary",
                "enabled": True,
                "request": {
                    "method": "post",
                    "url": "https://example.test/query/{qq}",
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
                "url": "https://example.test/query/$qq",
            },
        )


    def test_provider_tokens_save_hot_reload_without_returning_values(self):
        for provider_id, secret_name in (
            ("lolban-primary", "LOLMAP_API_TOKEN"),
            ("lolban-4png", "LOL_BAN_4PNG_TOKEN"),
        ):
            with self.subTest(provider_id=provider_id), patch(
                "lanzou_update_push_api_server.lolban_console.save_parser_secret",
                return_value={"ok": True, "message": "saved", "backup_path": "backup"},
            ) as save_secret, patch(
                "lanzou_update_push_api_server.lolban_console._main_request",
                return_value={"ok": True, "changed_environment": [secret_name]},
            ) as main_request:
                result = save_provider_secret(
                    "http://127.0.0.1:5001",
                    {"provider_id": provider_id, "value": "real-token"},
                )
            save_secret.assert_called_once_with(
                {"name": secret_name, "value": "real-token"}
            )
            self.assertEqual(
                main_request.call_args.kwargs["payload"],
                {"environment": {secret_name: "real-token"}},
            )
            self.assertTrue(result["ok"])
            self.assertNotIn("real-token", str(result))

    def test_fourpng_compatibility_endpoint_uses_provider_secret_path(self):
        with patch(
            "lanzou_update_push_api_server.lolban_console.save_provider_secret",
            return_value={"ok": True},
        ) as save_secret:
            result = save_fourpng_token("http://127.0.0.1:5001", {"value": "legacy-token"})
        self.assertTrue(result["ok"])
        save_secret.assert_called_once_with(
            "http://127.0.0.1:5001",
            {"provider_id": "lolban-4png", "value": "legacy-token"},
        )

    def test_test_modes_do_not_mix_provider_and_formal_results(self):
        with patch(
            "lanzou_update_push_api_server.lolban_console._main_request",
            return_value={"ok": True},
        ) as request:
            provider = test_lolban_console(
                "http://127.0.0.1:5001",
                {"mode": "provider", "qq": "97077000", "provider_id": "p1"},
            )
        self.assertIn("provider_test", provider)
        self.assertNotIn("formal_chain", provider)
        self.assertEqual(request.call_args.args[2], "/admin/query/lolban/provider-test")

    def test_missing_secret_has_actionable_safe_diagnostic(self):
        diagnostic = _provider_error_diagnostic(
            ParserConfigError("Secret 未配置：LOL_BAN_4PNG_TOKEN")
        )
        self.assertEqual(diagnostic["category"], "secret_not_loaded")
        self.assertIn("5001", diagnostic["message"])
        self.assertNotIn("LOL_BAN_4PNG_TOKEN", diagnostic["message"])

    def test_dedicated_page_contains_required_diagnostics(self):
        page = render_lolban_console_page()
        self.assertIn("封号查询配置与实时诊断", page)
        self.assertIn("Provider 直连", page)
        self.assertIn("5001 正式链路", page)
        self.assertIn("/admin/query-console/lolban/save", page)
        self.assertIn("/admin/query-console/lolban/test", page)
        self.assertIn("测试所选 Provider", page)
        self.assertIn("测试正式链路", page)
        self.assertIn("data-secret-provider", page)
        self.assertIn("providerSecrets", page)
        self.assertIn("/admin/query-console/lolban/provider-secret", page)
        self.assertIn("providerSecretControl", page)

    def test_root_dashboard_theme_injects_lolban_entry(self):
        page = apply_ios_glass_theme(
            '<!doctype html><html><head></head><body><div class="actions"></div></body></html>'
        )
        self.assertIn("dataset.queryConsoleLolban", page)
        self.assertIn("/query-console/lolban", page)
        self.assertIn("封号查询配置", page)


if __name__ == "__main__":
    unittest.main()
