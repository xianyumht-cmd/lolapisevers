import json
import unittest
from types import SimpleNamespace

from routers.groupguard_delivery import groupguard_query


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


class GroupGuardVideoRemovedTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_video_aliases_are_not_supported(self):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(ctx=object())),
            headers={},
        )
        for feature in ("video", "video_query", "我要看"):
            with self.subTest(feature=feature):
                response = await groupguard_query(
                    request,
                    {
                        "feature": feature,
                        "parameters": {"category": "热门"},
                        "preferred": "text",
                    },
                )
                body = decode(response)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(body["ok"])
                self.assertEqual(body["feature"], "unknown")
                self.assertEqual(body["error"]["code"], "invalid_query")
                self.assertIn("不支持", body["error"]["user_message"])


if __name__ == "__main__":
    unittest.main()
