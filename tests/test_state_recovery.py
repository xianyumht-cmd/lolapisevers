import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig
from lanzou_update_push_api_server.server import create_app
from lanzou_update_push_api_server.state_recovery import default_state, recover_state_file


class StateRecoveryTests(unittest.TestCase):
    def test_missing_state_is_left_for_normal_initialization(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"

            result = recover_state_file(state_path)

            self.assertEqual(result["action"], "missing")
            self.assertFalse(state_path.exists())

    def test_empty_state_is_backed_up_and_rebuilt(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text("", encoding="utf-8")

            result = recover_state_file(state_path)

            self.assertEqual(result["action"], "recovered")
            backup_path = Path(result["backup_path"])
            self.assertTrue(backup_path.exists())
            self.assertEqual(backup_path.read_text(encoding="utf-8"), "")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), default_state())

    def test_invalid_json_is_backed_up_and_rebuilt(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            original = '{"snapshots": '
            state_path.write_text(original, encoding="utf-8")

            result = recover_state_file(state_path)

            self.assertEqual(result["action"], "recovered")
            self.assertIn("JSONDecodeError", result["error"])
            self.assertEqual(Path(result["backup_path"]).read_text(encoding="utf-8"), original)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), default_state())

    def test_non_object_json_is_recovered(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text("[]", encoding="utf-8")

            result = recover_state_file(state_path)

            self.assertEqual(result["action"], "recovered")
            self.assertIn("ValueError", result["error"])
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), default_state())

    def test_valid_state_is_not_rewritten(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            original = {"version": 1, "snapshots": {"demo": {}}, "events": [], "last_scan": {}}
            state_path.write_text(json.dumps(original), encoding="utf-8")

            result = recover_state_file(state_path)

            self.assertEqual(result["action"], "valid")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original)
            self.assertEqual(list(Path(temp_dir).glob("state.json.bad.*")), [])

    def test_dashboard_starts_with_empty_state_file(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text("", encoding="utf-8")
            config = AppConfig(scan_on_start=False, state_path=state_path)

            with TestClient(create_app(config)) as client:
                response = client.get("/health")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["state_recovery"]["action"], "recovered")
            self.assertTrue(Path(payload["state_recovery"]["backup_path"]).exists())


if __name__ == "__main__":
    unittest.main()
