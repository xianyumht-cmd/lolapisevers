from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig, WatcherConfig
from lanzou_update_push_api_server.server import create_app


class ControlUiRouteTests(unittest.TestCase):
    def make_config(self, temp_dir: str) -> AppConfig:
        return AppConfig(
            scan_on_start=False,
            state_path=Path(temp_dir) / "state.json",
            watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
        )

    def test_new_root_operations_pages_assets_and_legacy_fallback_are_served(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app = create_app(self.make_config(temp_dir))

            with TestClient(app) as client:
                root = client.get("/")
                main_config = client.get("/main-config")
                lanzou_config = client.get("/lanzou/config")
                watchers = client.get("/lanzou/watchers")
                targets = client.get("/lanzou/targets")
                debugger = client.get("/api-debugger")
                logs = client.get("/logs")
                diagnostics = client.get("/diagnostics")
                system = client.get("/system")
                css = client.get("/control-assets/console.css")
                operations_css = client.get("/control-assets/operations.css")
                configuration_css = client.get("/control-assets/configuration.css")
                script = client.get("/control-assets/console.js")
                operations_script = client.get("/control-assets/operations.js")
                configuration_script = client.get("/control-assets/configuration.js")
                icons = client.get("/control-assets/icons.svg")
                legacy = client.get("/legacy-ui")
                legacy_tab = client.get("/?tab=logs", follow_redirects=False)

        self.assertEqual(root.status_code, 200)
        self.assertIn('data-console-ui="p0"', root.text)
        self.assertIn('/control-assets/console.js', root.text)
        self.assertIn('id="adminTokenDialog"', root.text)

        for response, marker in (
            (main_config, 'data-console-ui="main-config"'),
            (lanzou_config, 'data-console-ui="lanzou-config"'),
            (watchers, 'data-console-ui="watchers"'),
            (targets, 'data-console-ui="targets"'),
            (debugger, 'data-console-ui="api-debugger"'),
            (logs, 'data-console-ui="logs"'),
            (diagnostics, 'data-console-ui="diagnostics"'),
            (system, 'data-console-ui="system"'),
        ):
            self.assertEqual(response.status_code, 200)
            self.assertIn(marker, response.text)
            if marker in {'data-console-ui="logs"', 'data-console-ui="diagnostics"', 'data-console-ui="system"'}:
                self.assertIn('/control-assets/operations.js', response.text)
                self.assertIn('/control-assets/operations.css', response.text)
            else:
                self.assertIn('/control-assets/configuration.js', response.text)
                self.assertIn('/control-assets/configuration.css', response.text)
            self.assertNotIn('/control-assets/console.js', response.text)

        self.assertEqual(css.status_code, 200)
        self.assertIn('"Microsoft YaHei UI"', css.text)
        self.assertEqual(operations_css.status_code, 200)
        self.assertIn('.operations-console', operations_css.text)
        self.assertEqual(configuration_css.status_code, 200)
        self.assertIn('.configuration-grid', configuration_css.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn('/admin/overview', script.text)
        self.assertIn('sessionStorage', script.text)
        self.assertEqual(operations_script.status_code, 200)
        self.assertIn('/admin/diagnostics', operations_script.text)
        self.assertEqual(configuration_script.status_code, 200)
        self.assertIn('/admin/main-config', configuration_script.text)
        self.assertIn('/admin/invoke', configuration_script.text)
        self.assertIn('/admin/service/restart', operations_script.text)
        self.assertEqual(icons.status_code, 200)
        self.assertIn('icon-dashboard', icons.text)
        self.assertIn('icon-tool', icons.text)

        self.assertEqual(legacy.status_code, 200)
        self.assertNotIn('data-console-ui="p0"', legacy.text)
        self.assertEqual(legacy_tab.status_code, 307)
        self.assertEqual(legacy_tab.headers.get("location"), "/logs")

    def test_page_shells_and_assets_stay_public_when_admin_token_is_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"WEBUI_ADMIN_TOKEN": "configured-token"},
            clear=False,
        ):
            app = create_app(self.make_config(temp_dir))
            with TestClient(app) as client:
                root = client.get("/")
                main_config = client.get("/main-config")
                lanzou_config = client.get("/lanzou/config")
                watchers = client.get("/lanzou/watchers")
                targets = client.get("/lanzou/targets")
                debugger = client.get("/api-debugger")
                logs = client.get("/logs")
                diagnostics = client.get("/diagnostics")
                system = client.get("/system")
                css = client.get("/control-assets/console.css")
                operations_css = client.get("/control-assets/operations.css")
                configuration_css = client.get("/control-assets/configuration.css")
                script = client.get("/control-assets/console.js")
                operations_script = client.get("/control-assets/operations.js")
                configuration_script = client.get("/control-assets/configuration.js")
                icons = client.get("/control-assets/icons.svg")
                protected = client.get("/admin/logs")
                authorized = client.get(
                    "/admin/logs",
                    headers={"x-admin-token": "configured-token"},
                )

        for response in (root, main_config, lanzou_config, watchers, targets, debugger, logs, diagnostics, system, css, operations_css, configuration_css, script, operations_script, configuration_script, icons):
            self.assertEqual(response.status_code, 200)
        self.assertEqual(protected.status_code, 401)
        self.assertEqual(authorized.status_code, 200)


if __name__ == "__main__":
    unittest.main()
