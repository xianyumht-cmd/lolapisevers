import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class UpdateControlUiContractTests(unittest.TestCase):
    def test_release_ui_exposes_all_download_controls(self):
        script = (
            ROOT
            / "lanzou_update_push_api_server"
            / "control_ui"
            / "assets"
            / "release-update.js"
        ).read_text(encoding="utf-8")
        for control_id in [
            "releaseUpdatePauseButton",
            "releaseUpdateResumeButton",
            "releaseUpdateReconnectButton",
            "releaseUpdateResetButton",
        ]:
            self.assertIn(control_id, script)
        self.assertIn("后台 worker", script)
        self.assertIn("最近心跳", script)
        self.assertIn("pollRestartVerification", script)
        self.assertIn("stopImmediatePropagation", script)

    def test_control_routes_include_pause_resume_reconnect_and_reset(self):
        source = (
            ROOT / "lanzou_update_push_api_server" / "control_extensions.py"
        ).read_text(encoding="utf-8")
        for route in [
            '/admin/update/pause',
            '/admin/update/resume',
            '/admin/update/reconnect',
            '/admin/update/reset',
        ]:
            self.assertIn(route, source)


if __name__ == "__main__":
    unittest.main()
