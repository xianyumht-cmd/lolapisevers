import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routers.query_observability import query_observability
from services.query_observability import OBSERVABILITY_SCHEMA_VERSION


def request_with_ctx(ctx_marker=True):
    state = SimpleNamespace()
    if ctx_marker is not False:
        state.ctx = object() if ctx_marker is True else ctx_marker
    return SimpleNamespace(app=SimpleNamespace(state=state))


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


class QueryObservabilityRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_returns_sanitized_payload_without_network_probe(self):
        expected = {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "generated_at": "2026-07-29T06:00:00+00:00",
            "status": "degraded",
            "summary": {
                "live": 1,
                "cache": 1,
                "snapshot": 1,
                "stale": 1,
                "unavailable": 0,
            },
            "sources": {},
            "caches": {},
        }
        with patch(
            "routers.query_observability.build_query_observability",
            return_value=expected,
        ) as builder:
            response = await query_observability(request_with_ctx())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(decode(response), expected)
        builder.assert_called_once()
        self.assertIsNotNone(builder.call_args.args[0])

    async def test_missing_context_returns_http_503_and_safe_body(self):
        response = await query_observability(request_with_ctx(False))
        body = decode(response)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["schema_version"], OBSERVABILITY_SCHEMA_VERSION)
        self.assertEqual(body["status"], "down")
        self.assertEqual(body["error_class"], "context_unavailable")
        self.assertNotIn("error_message", body)


if __name__ == "__main__":
    unittest.main()
