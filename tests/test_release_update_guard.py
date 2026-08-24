import unittest
from unittest.mock import patch

from lanzou_update_push_api_server import release_update_guard as guard


class ReleaseUpdateGuardTests(unittest.TestCase):
    def _fresh(self, current="3" * 40, target="a" * 40):
        return {
            "ok": True,
            "current_commit": current,
            "current_release": "build-current",
            "latest_release": "lolapi-target",
            "latest_release_name": "lolapi-target",
            "target_commit": target,
            "package_name": "package.zip",
            "package_bytes": 123,
            "status": "update_available",
            "available": True,
            "update_state": {"status": "failed"},
        }

    def test_failed_persisted_state_refreshes_remote_and_blocks_older_release(self):
        previous = {
            "status": "failed",
            "target_commit": "a" * 40,
            "package": "old.zip",
            "error": "old failure",
        }
        with (
            patch.object(guard.core, "_read_state", return_value=previous),
            patch.object(guard.core, "release_update_status", return_value=self._fresh()),
            patch.object(guard, "_compare_release_relation", return_value="release_behind"),
            patch.object(guard.controller, "release_update_status") as local,
        ):
            result = guard.release_update_status()

        local.assert_not_called()
        self.assertEqual(result["status"], "current")
        self.assertFalse(result["available"])
        self.assertEqual(result["release_relation"], "release_behind")
        self.assertEqual(result["update_state"], {})
        self.assertEqual(result["last_update_state"], previous)
        self.assertIn("禁止降级", result["error"])
        self.assertFalse(any(result["controls"].values()))

    def test_forward_release_is_available_after_stale_failure(self):
        previous = {
            "status": "failed",
            "target_commit": "b" * 40,
            "package": "older.zip",
        }
        fresh = self._fresh(target="c" * 40)
        with (
            patch.object(guard.core, "_read_state", return_value=previous),
            patch.object(guard.core, "release_update_status", return_value=fresh),
            patch.object(guard, "_compare_release_relation", return_value="forward"),
        ):
            result = guard.release_update_status()

        self.assertEqual(result["status"], "update_available")
        self.assertTrue(result["available"])
        self.assertEqual(result["target_commit"], "c" * 40)
        self.assertEqual(result["update_state"], {})
        self.assertFalse(any(result["controls"].values()))

    def test_live_worker_remains_local_without_remote_refresh(self):
        local = {
            "update_state": {"status": "downloading"},
            "worker_alive": True,
            "status": "updating",
        }
        with (
            patch.object(guard.core, "_read_state", return_value={"status": "downloading"}),
            patch.object(guard.controller, "release_update_status", return_value=local),
            patch.object(guard.core, "release_update_status") as remote,
        ):
            result = guard.release_update_status()
        self.assertIs(result, local)
        remote.assert_not_called()

    def test_start_refuses_release_behind_without_starting_worker(self):
        guarded = {
            "status": "current",
            "available": False,
            "release_relation": "release_behind",
            "release_notice": "当前版本领先 Release",
        }
        with (
            patch.object(guard, "release_update_status", return_value=guarded),
            patch.object(guard.controller, "start_release_update") as start,
        ):
            with self.assertRaises(guard.ReleaseUpdateError):
                guard.start_release_update()
        start.assert_not_called()

    def test_unknown_saved_target_relation_blocks_reset_fail_closed(self):
        with (
            patch.object(guard, "_saved_target_relation", return_value="unknown"),
            patch.object(guard.controller, "reset_release_update") as reset,
        ):
            result = guard.reset_release_update()
        self.assertFalse(result["ok"])
        self.assertIn("禁止", result["error"])
        reset.assert_not_called()

    def test_compare_api_maps_github_status(self):
        class Response:
            ok = True

            def json(self):
                return {"status": "behind"}

        with (
            patch.object(guard.core, "_headers", return_value={}),
            patch.object(guard.requests, "get", return_value=Response()) as request,
        ):
            relation = guard._compare_release_relation("1" * 40, "2" * 40, "token")
        self.assertEqual(relation, "release_behind")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
