import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server import release_update_controller as controller


class ReleaseUpdateControllerTests(unittest.TestCase):
    def setUp(self):
        controller._PAUSE_EVENT.clear()
        controller._RECONNECT_EVENT.clear()
        controller._RESET_EVENT.clear()

    def tearDown(self):
        controller._PAUSE_EVENT.clear()
        controller._RECONNECT_EVENT.clear()
        controller._RESET_EVENT.clear()

    def test_persisted_downloading_state_from_old_process_becomes_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_path = root / "update-state.json"
            token_path = root / "github-release-token.txt"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "downloading",
                        "phase": "download",
                        "release": "lolapi-test",
                        "target_commit": "a" * 40,
                        "package": "LOLDataSystem-full-bug-repair-safe-deploy-aaaaaaaaaaaa-py311-py314-winps51-v3.zip",
                        "package_bytes": 100,
                        "downloaded_bytes": 20,
                        "worker_pid": os.getpid() + 9999,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(controller.core, "_STATE_PATH", state_path),
                patch.object(controller.core, "_TOKEN_PATH", token_path),
                patch.object(controller, "_worker_alive", return_value=False),
                patch.object(
                    controller,
                    "load_build_info",
                    return_value={"commit_sha": "b" * 40, "release": "old"},
                ),
                patch.object(controller.core, "_request_json") as request_json,
            ):
                result = controller.release_update_status()

            request_json.assert_not_called()
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["update_state"]["status"], "interrupted")
            self.assertFalse(result["worker_alive"])
            self.assertTrue(result["controls"]["can_resume"])
            self.assertTrue(result["controls"]["can_reconnect"])
            self.assertTrue(result["controls"]["can_reset"])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "interrupted")

    def test_live_worker_keeps_active_state_and_exposes_pause(self):
        state = {
            "status": "downloading",
            "phase": "download",
            "release": "lolapi-test",
            "target_commit": "a" * 40,
            "package": "package.zip",
            "package_bytes": 123,
            "worker_pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with (
            patch.object(controller.core, "_read_state", return_value=state),
            patch.object(controller, "_worker_alive", return_value=True),
            patch.object(
                controller,
                "load_build_info",
                return_value={"commit_sha": "b" * 40, "release": "old"},
            ),
        ):
            result = controller.release_update_status()
        self.assertEqual(result["status"], "updating")
        self.assertTrue(result["controls"]["can_pause"])
        self.assertFalse(result["controls"]["can_resume"])

    def test_pause_and_reconnect_set_cooperative_worker_events(self):
        with patch.object(controller, "_worker_alive", return_value=True):
            paused = controller.pause_release_update()
            self.assertTrue(paused["ok"])
            self.assertTrue(controller._PAUSE_EVENT.is_set())

            reconnected = controller.reconnect_release_update()
            self.assertTrue(reconnected["ok"])
            self.assertFalse(controller._PAUSE_EVENT.is_set())
            self.assertTrue(controller._RECONNECT_EVENT.is_set())

    def test_reset_removes_only_matching_package_under_update_home_then_restarts(self):
        package = "LOLDataSystem-full-bug-repair-safe-deploy-aaaaaaaaaaaa-py311-py314-winps51-v3.zip"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "release-1-aaaaaaaaaaaa"
            nested.mkdir()
            full = nested / package
            part = nested / f"{package}.part"
            full.write_bytes(b"full")
            part.write_bytes(b"partial")
            state = {
                "status": "interrupted",
                "target_commit": "a" * 40,
                "package": package,
            }
            with (
                patch.object(controller.core, "_UPDATE_HOME", root),
                patch.object(controller.core, "_read_state", return_value=state),
                patch.object(controller, "_worker_alive", return_value=False),
                patch.object(
                    controller,
                    "start_release_update",
                    return_value={"ok": True, "started": True},
                ) as start,
            ):
                result = controller.reset_release_update()
            self.assertTrue(result["ok"])
            start.assert_called_once_with()
            self.assertFalse(full.exists())
            self.assertFalse(part.exists())

    def test_low_speed_threshold_has_safe_lower_bound(self):
        with patch.dict(os.environ, {"LOLAPI_UPDATE_MIN_BPS": "1"}, clear=False):
            self.assertEqual(controller._min_speed_bps(), 4 * 1024)
        with patch.dict(os.environ, {"LOLAPI_UPDATE_LOW_SPEED_WINDOW": "1"}, clear=False):
            self.assertEqual(controller._low_speed_window_seconds(), 10.0)


if __name__ == "__main__":
    unittest.main()
