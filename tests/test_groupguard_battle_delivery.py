import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.responses import JSONResponse, Response

from routers.groupguard_delivery import groupguard_query
from services.battle_delivery import battle_meta, format_battle_text
from services.query_delivery import DELIVERY_PROTOCOL


def request_with_ctx(ctx=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx if ctx is not None else object())),
        headers={},
    )


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


BATTLE_PAYLOAD = {
    "name": "测试玩家#12345",
    "region": "艾欧尼亚",
    "level": 123,
    "rank": "钻石 IV 25 LP",
    "ranked_queues": [],
    "last_online_time": "2026-07-29 18:00:00",
    "winrate_recent": "60.0%",
    "avg_kda_recent": 4.25,
    "recent_matches": [
        {
            "game_time": "2026-07-29 17:30:00",
            "champion": "亚索",
            "kills": 10,
            "deaths": 2,
            "assists": 8,
            "kda": 9.0,
            "win": True,
            "duration": 1800,
            "queue": "单双排",
        }
    ],
    "source": "live",
    "is_stale": False,
    "snapshot_updated_at": "",
    "cache_expires_in": 300,
}


class GroupGuardBattleDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_battle_auto_returns_service_rendered_image(self):
        image = b"\x89PNG\r\nbattle-image"
        with patch(
            "routers.groupguard_delivery.query_cross",
            new=AsyncMock(return_value=BATTLE_PAYLOAD),
        ) as query, patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(return_value=Response(content=image, media_type="image/png")),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "battle",
                    "parameters": {"name": "测试玩家#12345", "region": "艾欧尼亚"},
                    "preferred": "auto",
                    "capabilities": {"image": True, "text": True, "forward": True},
                    "request_id": "plugin-battle-001",
                },
            )

        query.assert_awaited_once_with(
            unittest.mock.ANY,
            name="测试玩家#12345",
            region="艾欧尼亚",
            output_format="pretty",
        )
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "battle")
        segment = body["delivery"]["segments"][0]
        self.assertEqual(segment["type"], "image")
        self.assertEqual(base64.b64decode(segment["data"]), image)
        self.assertEqual(body["meta"]["player"]["name"], "测试玩家#12345")
        self.assertNotIn("recent_matches", body)

    async def test_battle_image_failure_falls_back_to_service_text(self):
        with patch(
            "routers.groupguard_delivery.query_cross",
            new=AsyncMock(return_value=BATTLE_PAYLOAD),
        ), patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(
                return_value=JSONResponse(status_code=500, content={"error": "secret renderer path"})
            ),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "查战绩",
                    "parameters": {"player_id": "测试玩家#12345", "region": "艾欧尼亚"},
                    "preferred": "image",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "battle")
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertIn("战绩查询｜测试玩家#12345", body["delivery"]["segments"][0]["text"])
        self.assertIn("1. 胜利｜亚索", body["delivery"]["segments"][0]["text"])
        self.assertEqual(body["meta"]["delivery_fallback"], "image_render_failed")
        self.assertNotIn("secret renderer path", str(body))

    async def test_battle_requires_player_name(self):
        response = await groupguard_query(
            request_with_ctx(),
            {"feature": "battle", "parameters": {}, "preferred": "text"},
        )
        body = decode(response)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_query")
        self.assertIn("玩家ID", body["error"]["user_message"])

    def test_snapshot_text_and_meta_are_channel_neutral(self):
        payload = {
            **BATTLE_PAYLOAD,
            "source": "snapshot",
            "is_stale": True,
            "snapshot_updated_at": "2026-07-29 17:00:00",
        }
        text = format_battle_text(payload)
        meta = battle_meta(payload)
        self.assertIn("正在使用历史快照", text)
        self.assertTrue(meta["stale"])
        self.assertEqual(meta["source"], "snapshot")
        self.assertNotIn("OneBot", text)
        self.assertNotIn("CQ:", text)


if __name__ == "__main__":
    unittest.main()
