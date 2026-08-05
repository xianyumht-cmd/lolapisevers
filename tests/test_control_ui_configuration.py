from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lanzou_update_push_api_server import management
from lanzou_update_push_api_server.config import (
    AppConfig,
    NotifyTargetConfig,
    WatcherConfig,
    sanitized_config,
)
from lanzou_update_push_api_server.control_extensions import _migrated_tab_target
from lanzou_update_push_api_server.control_ui import (
    ASSET_DIRECTORY,
    render_debugger_page,
    render_lanzou_config_page,
    render_main_config_page,
    render_targets_page,
    render_watchers_page,
)


class _Url:
    def __init__(self, path: str) -> None:
        self.path = path


class _Request:
    def __init__(self, path: str, tab: str = "") -> None:
        self.url = _Url(path)
        self.query_params = {"tab": tab} if tab else {}


class ControlUiConfigurationTests(unittest.TestCase):
    def test_pages_use_shared_shell_real_routes_and_configuration_assets(self) -> None:
        cases = (
            (render_main_config_page(), "main-config", "主接口配置", "mainConfigForm"),
            (render_lanzou_config_page(), "lanzou-config", "蓝奏全局配置", "lzWerEndpoint"),
            (render_watchers_page(), "watchers", "监控项目", "watcherRows"),
            (render_targets_page(), "targets", "通知目标", "targetRows"),
            (render_debugger_page(), "api-debugger", "接口调试器", "debuggerRouteSelect"),
        )
        for html, active, title, marker in cases:
            with self.subTest(active=active):
                self.assertIn(f'data-console-ui="{active}"', html)
                self.assertIn(title, html)
                self.assertIn(f'id="{marker}"', html)
                self.assertIn('/control-assets/configuration.css', html)
                self.assertIn('/control-assets/configuration.js', html)
                self.assertNotIn('/control-assets/console.js', html)
                self.assertEqual(html.count('aria-current="page"'), 1)
                self.assertNotIn('href="/legacy-ui"', html)
                self.assertNotIn('/?tab=', html)

    def test_configuration_script_uses_real_apis_and_custom_dialogs(self) -> None:
        script = (ASSET_DIRECTORY / "configuration.js").read_text(encoding="utf-8")
        for endpoint in (
            "/admin/main-config",
            "/admin/lanzou-config",
            "/admin/overview",
            "/scan?watcher_id=",
            "/notify/test",
            "/files/",
            "/admin/openapi/main",
            "/admin/openapi/lanzou",
            "/admin/invoke",
        ):
            self.assertIn(endpoint, script)
        self.assertIn("password_configured", script)
        self.assertIn("clear_password", script)
        self.assertIn('text == "***"', Path("lanzou_update_push_api_server/management.py").read_text(encoding="utf-8"))
        self.assertIn("showModal()", script)
        self.assertIn("sessionStorage", script)
        self.assertNotIn("alert(", script)
        self.assertNotIn("confirm(", script)
        self.assertNotIn("prompt(", script)

    def test_all_legacy_runtime_tabs_redirect_to_new_pages(self) -> None:
        expected = {
            "overview": "/",
            "mainconfig": "/main-config",
            "lanzouconfig": "/lanzou/config",
            "watchers": "/lanzou/watchers",
            "targets": "/lanzou/targets",
            "debugger": "/api-debugger",
            "logs": "/logs",
            "diagnostics": "/diagnostics",
            "system": "/system",
        }
        for tab, target in expected.items():
            with self.subTest(tab=tab):
                self.assertEqual(_migrated_tab_target(_Request("/", tab)), target)
        self.assertIsNone(_migrated_tab_target(_Request("/parser-center", "mainconfig")))
        self.assertIsNone(_migrated_tab_target(_Request("/", "unknown")))

    def test_sanitized_lanzou_config_masks_all_editable_secrets(self) -> None:
        config = AppConfig(
            wer_api_key="secret-api-key",
            wer_api_url_param="share_url",
            wer_api_password_param="share_password",
            watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test", password="1234")],
            notify_targets=[NotifyTargetConfig(name="target", url="http://127.0.0.1:6108/", headers={"x-token": "secret"})],
        )
        payload = sanitized_config(config)
        self.assertTrue(payload["wer_api_key_configured"])
        self.assertNotIn("wer_api_key", payload)
        self.assertEqual(payload["wer_api_url_param"], "share_url")
        self.assertEqual(payload["wer_api_password_param"], "share_password")
        self.assertEqual(payload["watchers"][0]["password"], "")
        self.assertTrue(payload["watchers"][0]["password_configured"])
        self.assertEqual(payload["notify_targets"][0]["headers"]["x-token"], "***")
        self.assertNotIn("secret-api-key", json.dumps(payload))
        self.assertNotIn("1234", json.dumps(payload))
        self.assertNotIn('"secret"', json.dumps(payload))

    def test_masked_watcher_and_target_round_trip_preserves_existing_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "watchers": [{
                    "id": "demo",
                    "title": "Demo",
                    "url": "https://example.test/share",
                    "password": "existing-password",
                    "enabled": True,
                    "max_pages": 20,
                }],
                "notify_targets": [{
                    "name": "target",
                    "enabled": True,
                    "url": "http://127.0.0.1:6108/",
                    "timeout_seconds": 8,
                    "headers": {"x-token": "existing-token", "x-mode": "old"},
                }],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"LANZOU_MONITOR_CONFIG": str(path)}, clear=False):
                management.update_lanzou_config({
                    "watchers": [{
                        "id": "demo",
                        "title": "Renamed",
                        "url": "https://example.test/share",
                        "enabled": True,
                        "max_pages": 25,
                    }],
                    "notify_targets": [{
                        "name": "target",
                        "enabled": True,
                        "url": "http://127.0.0.1:6108/",
                        "timeout_seconds": 9,
                        "headers": {"x-token": "***", "x-mode": "new"},
                    }],
                })
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["watchers"][0]["password"], "existing-password")
        self.assertEqual(saved["notify_targets"][0]["headers"]["x-token"], "existing-token")
        self.assertEqual(saved["notify_targets"][0]["headers"]["x-mode"], "new")


if __name__ == "__main__":
    unittest.main()
