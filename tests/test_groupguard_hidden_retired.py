import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from routers.groupguard_delivery import groupguard_query
from services.query_delivery import DELIVERY_PROTOCOL


def request_with_ctx():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=object())),
        headers={},
    )


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


class GroupGuardHiddenRetiredTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_aliases_are_rejected_without_upstream_query(self):
        aliases = ("hidden", "hidden_query", "查隐藏")
        for index, feature in enumerate(aliases, start=1):
            with self.subTest(feature=feature), patch(
                "routers.groupguard_delivery.query_cross",
                new=AsyncMock(
                    side_effect=AssertionError(
                        "retired hidden query must not call upstream"
                    )
                ),
            ) as query:
                response = await groupguard_query(
                    request_with_ctx(),
                    {
                        "feature": feature,
                        "parameters": {"name": "TheShy", "region": "1"},
                        "preferred": "text",
                        "capabilities": {
                            "text": True,
                            "image": True,
                            "forward": True,
                        },
                        "request_id": f"retired-hidden-{index}",
                    },
                )

            query.assert_not_awaited()
            body = decode(response)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
            self.assertFalse(body["ok"])
            self.assertEqual(body["feature"], "unknown")
            self.assertEqual(body["error"]["code"], "invalid_query")
            self.assertIn("不支持", body["error"]["user_message"])


if __name__ == "__main__":
    unittest.main()
