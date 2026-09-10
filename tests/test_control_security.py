import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from lanzou_update_push_api_server import maintenance
from lanzou_update_push_api_server.config import AppConfig
from lanzou_update_push_api_server.server import create_app


class ControlSecurityTests(unittest.TestCase):
    def make_app(self, state_path: Path):
        return create_app(AppConfig(scan_on_start=False, state_path=state_path))

    def test_public_pages_and_read_only_assets_remain_available_without_token(self):
        with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": ""}, clear=False):
            app = self.make_app(Path(temp_dir) / "state.json")
            with TestClient(app) as client:
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/lol-patch").status_code, 200)
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/security/status").status_code, 200)
                self.assertEqual(client.get("/control-assets/console.css").status_code, 200)
                self.assertEqual(client.get("/control-assets/console.js").status_code, 200)
                self.assertEqual(client.get("/control-assets/icons.svg").status_code, 200)

    def test_asset_prefix_does_not_make_neighboring_admin_paths_public(self):
        with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": ""}, clear=False):
            app = self.make_app(Path(temp_dir) / "state.json")
            with TestClient(app) as client:
                denied = client.get("/control-assets-admin")

        self.assertEqual(denied.status_code, 403)

    def test_non_loopback_control_access_is_rejected_without_token(self):
        with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": ""}, clear=False):
            audit_path = Path(temp_dir) / "audit.jsonl"
            with patch.object(maintenance, "AUDIT_PATH", audit_path):
                app = self.make_app(Path(temp_dir) / "state.json")
                with TestClient(app) as client:
                    response = client.get("/admin/main-config")

            self.assertEqual(response.status_code, 403)
            self.assertTrue(audit_path.exists())
            self.assertIn("authorization_denied", audit_path.read_text(encoding="utf-8"))

    def test_configured_token_is_required_and_accepted(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"WEBUI_ADMIN_TOKEN": "correct-token"},
            clear=False,
        ):
            app = self.make_app(Path(temp_dir) / "state.json")
            with TestClient(app) as client:
                patch_page = client.get("/lol-patch")
                update_denied = client.get("/admin/update/status")
                denied = client.get("/admin/main-config")
                allowed = client.get(
                    "/admin/main-config",
                    headers={"x-admin-token": "correct-token"},
                )

            self.assertEqual(patch_page.status_code, 200)
            self.assertEqual(update_denied.status_code, 401)
            self.assertEqual(denied.status_code, 401)
            self.assertEqual(allowed.status_code, 200)
            self.assertTrue(allowed.json()["ok"])


if __name__ == "__main__":
    unittest.main()
