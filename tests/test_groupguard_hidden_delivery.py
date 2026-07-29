import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from routers.groupguard_delivery import groupguard_query
from services.hidden_delivery import format_hidden_text, hidden_meta
from services.query_delivery import DELIVERY_PROTOCOL


def request_with_ctx(ctx=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx if ctx is not None else object())),
        headers={},
    )


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


HIDDEN_PAYLOAD = {
    "name": "隐藏玩家",
    "region": "艾欧尼亚",
    "level": 88,
    "rank": "铂金 I 50 LP",
    "last_online_time": "2026-07-29 19:00:00",
    "winrate_recent": "55.0%",
    "avg_kda_recent": 3.75,
    "recent_matches": [
        {
            "champion": "亚索",
            "kills": 8,
            "deaths": 4,
            "assists": 6,
            "win": True,
        },
        {
            "champion": "永恩",
            "kills": 3,
            "deaths": 7,
            "assists": 4,
            "win": False,
        },
    ],
    "source": "live",
    "is_stale": False,
    "snapshot_updated_at": "",
    "cache_expires_in": 180,
}


class GroupGuardHiddenDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_returns_final_text_and_uses_cross_service_once(self):
        with patch(
            "routers.groupguard_delivery.query_cross",
            new=AsyncMock(return_value=HIDDEN_PAYLOAD),
        ) as query, patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(side_effect=AssertionError("hidden must not render an image")),
        ) as renderer:
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "hidden",
                    "parameters": {"name": "隐藏玩家", "region": "艾欧尼亚"},
                    "preferred": "auto",
                    "capabilities": {"image": True, "text": True, "forward": True},
                    "request_id": "plugin-hidden-001",
                },
            )

        query.assert_awaited_once_with(
            unittest.mock.ANY,
            name="隐藏玩家",
            region="艾欧尼亚",
            output_format="pretty",
        )
        renderer.assert_not_awaited()
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "hidden")
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        text = body["delivery"]["segments"][0]["text"]
        self.assertIn("隐藏战绩｜隐藏玩家", text)
        self.assertIn("近期英雄：亚索、永恩", text)
        self.assertEqual(body["meta"]["count"], 2)
        self.assertNotIn("recent_matches", body)

    async def test_hidden_preferred_image_falls_back_to_safe_text(self):
        with patch(
            "routers.groupguard_delivery.query_cross",
            new=AsyncMock(return_value=HIDDEN_PAYLOAD),
        ), patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(side_effect=AssertionError("hidden must not render an image")),
        ) as renderer:
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "查隐藏",
                    "parameters": {"name": "隐藏玩家", "region": "1"},
                    "preferred": "image",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )

        renderer.assert_not_awaited()
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "hidden")
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertEqual(body["meta"]["delivery_fallback"], "image_not_supported")

    async def test_hidden_requires_name(self):
        response = await groupguard_query(
            request_with_ctx(),
            {"feature": "hidden", "parameters": {}, "preferred": "text"},
        )
        body = decode(response)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_query")
        self.assertIn("召唤师", body["error"]["user_message"])

    async def test_hidden_can_choose_forward_delivery(self):
        with patch(
            "routers.groupguard_delivery.query_cross",
            new=AsyncMock(return_value=HIDDEN_PAYLOAD),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "hidden_query",
                    "parameters": {"player_id": "隐藏玩家", "region": "艾欧尼亚"},
                    "preferred": "forward",
                    "capabilities": {"image": False, "text": False, "forward": True},
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["delivery"]["kind"], "forward")
        self.assertEqual(body["delivery"]["segments"][0]["type"], "forward")

    def test_hidden_snapshot_text_and_meta(self):
        payload = {
            **HIDDEN_PAYLOAD,
            "source": "snapshot",
            "is_stale": True,
            "snapshot_updated_at": "2026-07-29 18:30:00",
        }
        text = format_hidden_text(payload)
        meta = hidden_meta(payload, delivery_fallback="image_not_supported")
        self.assertIn("正在使用历史快照", text)
        self.assertTrue(meta["stale"])
        self.assertEqual(meta["source"], "snapshot")
        self.assertEqual(meta["delivery_fallback"], "image_not_supported")
        self.assertNotIn("OneBot", text)
        self.assertNotIn("CQ:", text)


if __name__ == "__main__":
    unittest.main()
