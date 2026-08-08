import unittest
from unittest.mock import patch

from lanzou_update_push_api_server.api_debugger import invoke_api


class ApiDebuggerTests(unittest.TestCase):
    def test_path_parameters_are_substituted_and_removed_from_query(self):
        class FakeResponse:
            ok = True
            status_code = 200
            headers = {"content-type": "application/json"}
            text = '{"ok":true}'
            content = text.encode("utf-8")
            url = "http://127.0.0.1:6178/files/demo%20id?limit=5"

            @staticmethod
            def json():
                return {"ok": True}

        with patch("lanzou_update_push_api_server.api_debugger.requests.request", return_value=FakeResponse()) as request_mock:
            result = invoke_api(
                "http://127.0.0.1:6178",
                {
                    "method": "GET",
                    "path": "/files/{watcher_id}",
                    "query": {"watcher_id": "demo id", "limit": 5},
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(request_mock.call_args.args[1], "http://127.0.0.1:6178/files/demo%20id")
        self.assertEqual(request_mock.call_args.kwargs["params"], {"limit": 5})

    def test_unfilled_path_parameter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "path parameter is not filled"):
            invoke_api(
                "http://127.0.0.1:6178",
                {
                    "method": "GET",
                    "path": "/files/{watcher_id}",
                    "query": {"watcher_id": "<watcher_id>"},
                },
            )

    def test_custom_headers_are_forwarded_and_sensitive_output_is_redacted(self):
        class FakeResponse:
            ok = True
            status_code = 200
            headers = {
                "content-type": "application/json",
                "set-cookie": "session=secret-cookie",
                "x-request-id": "demo",
            }
            content = b'{"ok":true}'
            url = "http://127.0.0.1:6178/admin/audit?token=secret-query&limit=5"

        with patch("lanzou_update_push_api_server.api_debugger.requests.request", return_value=FakeResponse()) as request_mock:
            result = invoke_api(
                "http://127.0.0.1:6178",
                {
                    "method": "GET",
                    "path": "/admin/audit",
                    "query": {"limit": 5},
                    "headers": {"x-client": "webui", "authorization": "Bearer secret"},
                },
                admin_token="internal-admin-token",
            )

        sent_headers = request_mock.call_args.kwargs["headers"]
        self.assertEqual(sent_headers["x-client"], "webui")
        self.assertEqual(sent_headers["authorization"], "Bearer secret")
        self.assertEqual(sent_headers["x-admin-token"], "internal-admin-token")
        self.assertEqual(result["headers"]["set-cookie"], "***")
        self.assertEqual(result["headers"]["x-request-id"], "demo")
        self.assertNotIn("secret-query", result["request_url"])
        self.assertIn("token=%2A%2A%2A", result["request_url"])

    def test_hop_by_hop_and_host_headers_are_rejected(self):
        for name in ("host", "content-length", "connection"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "not allowed"):
                    invoke_api(
                        "http://127.0.0.1:6178",
                        {
                            "method": "GET",
                            "path": "/health",
                            "headers": {name: "unsafe"},
                        },
                    )


if __name__ == "__main__":
    unittest.main()
