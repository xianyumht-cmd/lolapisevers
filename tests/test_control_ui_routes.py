from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig, WatcherConfig
from lanzou_update_push_api_server.server import create_app


class ControlUiRouteTests(unittest.TestCase):
    def test_new_root_assets_and_legacy_fallback_are_served(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = AppConfig(
                scan_on_start=False,
                state_path=Path(temp_dir) / "state.json",
                watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
            )
            app = create_app(config)

            with TestClient(app) as client:
                root = client.get("/")
                css = client.get("/control-assets/console.css")
                script = client.get("/control-assets/console.js")
                icons = client.get("/control-assets/icons.svg")
                legacy = client.get("/legacy-ui")
                legacy_tab = client.get("/?tab=logs")

        self.assertEqual(root.status_code, 200)
        self.assertIn('data-console-ui="p0"', root.text)
        self.assertIn('/control-assets/console.js', root.text)

        self.assertEqual(css.status_code, 200)
        self.assertIn('"Microsoft YaHei UI"', css.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn('/admin/overview', script.text)
        self.assertEqual(icons.status_code, 200)
        self.assertIn('icon-dashboard', icons.text)

        self.assertEqual(legacy.status_code, 200)
        self.assertNotIn('data-console-ui="p0"', legacy.text)
        self.assertEqual(legacy_tab.status_code, 200)
        self.assertNotIn('data-console-ui="p0"', legacy_tab.text)


if __name__ == "__main__":
    unittest.main()
