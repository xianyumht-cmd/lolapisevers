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


if __name__ == "__main__":
    unittest.main()
