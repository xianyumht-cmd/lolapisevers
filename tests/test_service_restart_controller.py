import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lanzou_update_push_api_server import service_restart_controller as controller


class ServiceRestartControllerTests(unittest.TestCase):
    def test_query_service_parses_queryex_pid_and_state(self):
        output = """SERVICE_NAME: LOLDataSystem\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : 4  RUNNING\n        PID                : 4321\n"""
        completed = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(controller.os, "name", "nt"), patch.object(
            controller.subprocess,
            "run",
            return_value=completed,
        ):
            result = controller._query_service()
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["process_id"], 4321)

    def test_status_marks_restart_verified_only_after_pid_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            marker_path = Path(temp) / "service-restart.json"
            marker_path.write_text(
                json.dumps(
                    {
                        "request_id": "req-1",
                        "status": "scheduled",
                        "before_pid": 111,
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(controller, "RESTART_STATE_PATH", marker_path),
                patch.object(
                    controller,
                    "_query_service",
                    return_value={
                        "ok": True,
                        "supported": True,
                        "service": "LOLDataSystem",
                        "state": "running",
                        "process_id": 222,
                        "detail": "",
                    },
                ),
            ):
                result = controller.windows_service_status()
        verification = result["restart_verification"]
        self.assertEqual(verification["status"], "verified")
        self.assertEqual(verification["before_pid"], 111)
        self.assertEqual(verification["after_pid"], 222)

    def test_unchanged_pid_after_timeout_is_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            marker_path = Path(temp) / "service-restart.json"
            marker_path.write_text(
                json.dumps(
                    {
                        "request_id": "req-2",
                        "status": "scheduled",
                        "before_pid": 333,
                        "requested_at": (
                            datetime.now(timezone.utc) - timedelta(seconds=90)
                        ).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(controller, "RESTART_STATE_PATH", marker_path),
                patch.object(
                    controller,
                    "_query_service",
                    return_value={
                        "ok": True,
                        "supported": True,
                        "service": "LOLDataSystem",
                        "state": "running",
                        "process_id": 333,
                        "detail": "",
                    },
                ),
            ):
                result = controller.windows_service_status()
        self.assertEqual(result["restart_verification"]["status"], "unverified")
        self.assertEqual(result["restart_verification"]["after_pid"], 333)

    def test_schedule_records_before_pid_and_does_not_claim_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            marker_path = Path(temp) / "service-restart.json"
            fake_process = SimpleNamespace(pid=9876)
            with (
                patch.object(controller.os, "name", "nt"),
                patch.object(controller, "RESTART_STATE_PATH", marker_path),
                patch.object(
                    controller,
                    "_query_service",
                    return_value={
                        "ok": True,
                        "supported": True,
                        "service": "LOLDataSystem",
                        "state": "running",
                        "process_id": 444,
                        "detail": "",
                    },
                ),
                patch.object(controller.subprocess, "Popen", return_value=fake_process),
            ):
                result = controller.schedule_windows_service_restart(delay_seconds=2)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertTrue(result["scheduled"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["before_pid"], 444)
        self.assertEqual(marker["status"], "scheduled")
        self.assertEqual(marker["launcher_pid"], 9876)


if __name__ == "__main__":
    unittest.main()
