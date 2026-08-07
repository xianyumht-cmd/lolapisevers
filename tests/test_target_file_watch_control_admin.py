from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from lanzou_update_push_api_server.target_file_watch_admin import (
    TargetFileWatchAdminError,
    check_target_file_watch_now,
    read_target_file_watch_overview,
    rebaseline_target_file_watch,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class TargetFileWatchControlAdminTests(unittest.TestCase):
    def test_overview_uses_server_side_control_token_without_exposing_it(self) -> None:
        response = _FakeResponse(200, {
            "ok": True,
            "running": True,
            "config": {
                "enabled": True,
                "source_url": "https://demo.lanzn.com/folder",
                "callback_url": "http://192.168.3.89:6108/api/target-file-push/event",
                "callback_token_configured": True,
                "check_interval_seconds": 300,
            },
            "baseline": {"provider": "wer", "file_count": 2, "files": []},
        })
        with patch.dict(os.environ, {"GROUPGUARD_WRITE_TOKEN": "server-secret"}, clear=False), patch(
            "lanzou_update_push_api_server.target_file_watch_admin.requests.request",
            return_value=response,
        ) as request_mock:
            payload = read_target_file_watch_overview("http://127.0.0.1:5001")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["configAuthority"], "GroupGuard 6108")
        self.assertNotIn("server-secret", repr(payload))
        call = request_mock.call_args
        self.assertEqual(call.args[0], "GET")
        self.assertEqual(call.args[1], "http://127.0.0.1:5001/api/v1/target-file-watch/status")
        self.assertEqual(call.kwargs["headers"]["x-groupguard-token"], "server-secret")

    def test_actions_use_post_and_expected_paths(self) -> None:
        response = _FakeResponse(200, {"ok": True, "state": "unchanged"})
        with patch(
            "lanzou_update_push_api_server.target_file_watch_admin.requests.request",
            return_value=response,
        ) as request_mock:
            check_target_file_watch_now("http://127.0.0.1:5001")
            rebaseline_target_file_watch("http://127.0.0.1:5001")

        calls = request_mock.call_args_list
        self.assertEqual(calls[0].args[:2], ("POST", "http://127.0.0.1:5001/api/v1/target-file-watch/check"))
        self.assertEqual(calls[1].args[:2], ("POST", "http://127.0.0.1:5001/api/v1/target-file-watch/rebaseline"))

    def test_upstream_error_is_sanitized(self) -> None:
        response = _FakeResponse(401, {"detail": "unauthorized"})
        with patch(
            "lanzou_update_push_api_server.target_file_watch_admin.requests.request",
            return_value=response,
        ):
            with self.assertRaisesRegex(TargetFileWatchAdminError, "HTTP 401"):
                read_target_file_watch_overview("http://127.0.0.1:5001")

    def test_non_json_response_is_rejected(self) -> None:
        response = _FakeResponse(200, ValueError("bad json"))
        with patch(
            "lanzou_update_push_api_server.target_file_watch_admin.requests.request",
            return_value=response,
        ):
            with self.assertRaisesRegex(TargetFileWatchAdminError, "非 JSON"):
                read_target_file_watch_overview("http://127.0.0.1:5001")


if __name__ == "__main__":
    unittest.main()
