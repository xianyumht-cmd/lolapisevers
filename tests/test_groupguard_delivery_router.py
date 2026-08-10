import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from routers.groupguard_delivery import groupguard_query
from services.query_delivery import DELIVERY_PROTOCOL


def request_with_ctx(ctx=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx if ctx is not None else object())),
        headers={},
    )


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


SHARD_PAYLOAD = {
    "hero": {"alias": "Kalista", "name": "卡莉丝塔", "title": "复仇之矛"},
    "pick_rate": 0.12,
    "win_rate": 0.51,
    "count": 1,
    "rows": [{"name": "测试合集", "pick_rate": 0.8, "win_rate": 0.6}],
    "source": "live",
    "provider": "badspacebar",
    "stale": False,
}

ARAM_PAYLOAD = {
    "hero": {"alias": "Ahri", "name": "阿狸", "title": "九尾妖狐"},
    "rows": [{"name": "测试强化", "rarity": "gold", "performance": 0.6, "popular": 0.4}],
    "item_builds": [],
    "starter_items": [],
    "boots": [],
    "summoner_spells": [],
    "skill_order": [],
    "total": 1,
    "source": "opgg",
    "provider": "opgg",
    "stale": False,
}

ARAM_BALANCE = {
    "status": "ok",
    "complete": True,
    "scope": "aram",
    "provider": "opgg",
    "items": [
        {
            "key": "healing",
            "label": "治疗",
            "value": "-20%",
            "direction": "debuff",
        }
    ],
    "buffs": [],
    "debuffs": [
        {
            "key": "healing",
            "label": "治疗",
            "value": "-20%",
            "direction": "debuff",
        }
    ],
    "summary": "治疗 -20%",
    "stale": False,
}


class GroupGuardDeliveryRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_shard_auto_returns_final_image_segment(self):
        image = b"\x89PNG\r\nshard-image"
        with patch(
            "routers.groupguard_delivery.query_shard",
            new=AsyncMock(return_value=SHARD_PAYLOAD),
        ), patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(return_value=Response(content=image, media_type="image/png")),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "shard",
                    "parameters": {"hero": "滑板鞋"},
                    "preferred": "auto",
                    "capabilities": {"image": True, "text": True, "forward": True},
                    "request_id": "plugin-1",
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "shard")
        segment = body["delivery"]["segments"][0]
        self.assertEqual(segment["type"], "image")
        self.assertEqual(base64.b64decode(segment["data"]), image)
        self.assertEqual(body["meta"]["hero"]["alias"], "Kalista")
        self.assertNotIn("rows", body)

    async def test_aram_command_enriches_image_payload_with_balance(self):
        image = b"\x89PNG\r\naram-image"
        renderer = AsyncMock(return_value=Response(content=image, media_type="image/png"))
        with patch(
            "routers.groupguard_delivery.query_aram_augments",
            new=AsyncMock(return_value=ARAM_PAYLOAD),
        ), patch(
            "routers.groupguard_delivery.query_aram_balance",
            new=AsyncMock(return_value=ARAM_BALANCE),
        ) as balance_query, patch(
            "routers.groupguard_delivery._render_feature_image",
            new=renderer,
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "aram",
                    "parameters": {"hero": "阿狸"},
                    "preferred": "image",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["delivery"]["segments"][0]["type"], "image")
        balance_query.assert_awaited_once()
        rendered_payload = renderer.await_args.args[2]
        self.assertEqual(rendered_payload["balance"]["summary"], "治疗 -20%")
        self.assertEqual(rendered_payload["balance"]["scope"], "aram")

    async def test_aram_image_failure_falls_back_to_service_text(self):
        with patch(
            "routers.groupguard_delivery.query_aram_augments",
            new=AsyncMock(return_value=ARAM_PAYLOAD),
        ), patch(
            "routers.groupguard_delivery.query_aram_balance",
            new=AsyncMock(return_value=ARAM_BALANCE),
        ), patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(
                return_value=JSONResponse(status_code=500, content={"error": "secret renderer path"})
            ),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "aram",
                    "parameters": {"hero": "阿狸"},
                    "preferred": "image",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertIn("测试强化", body["delivery"]["segments"][0]["text"])
        self.assertEqual(body["meta"]["delivery_fallback"], "image_render_failed")
        self.assertNotIn("secret renderer path", str(body))

    async def test_lolban_explicit_text_returns_final_text_without_business_parsing(self):
        payload = {
            "code": 200,
            "by": "provider-a",
            "msg": "此账号状态正常",
            "data": {
                "qq": "2621735529",
                "ban_time": "",
                "end_time": "账号状态正常",
                "status": "正常",
            },
            "source": "stale",
            "stale_origin": "persistent_snapshot",
            "stale_age_seconds": 30,
        }
        with patch(
            "routers.groupguard_delivery.get_lolban_result",
            new=AsyncMock(return_value=(payload, "stale", 0)),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "lolban",
                    "parameters": {"qq": "2621735529"},
                    "preferred": "text",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )

        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertIn("账号状态：正常", body["delivery"]["segments"][0]["text"])
        self.assertEqual(body["meta"]["stale_origin"], "persistent_snapshot")
        self.assertNotIn("data", body)

    async def test_invalid_feature_returns_user_visible_non_retryable_error(self):
        response = await groupguard_query(
            request_with_ctx(),
            {"feature": "unknown", "parameters": {}},
        )
        body = decode(response)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_query")
        self.assertFalse(body["retry"]["allowed"])
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")

    async def test_not_found_is_not_retryable_and_keeps_safe_detail(self):
        with patch(
            "routers.groupguard_delivery.query_shard",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="未找到英雄：不存在")),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {"feature": "shard", "parameters": {"hero": "不存在"}},
            )
        body = decode(response)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "not_found")
        self.assertFalse(body["retry"]["allowed"])
        self.assertIn("未找到英雄", body["error"]["user_message"])

    async def test_service_failure_hides_exception_and_is_retryable(self):
        with patch(
            "routers.groupguard_delivery.query_shard",
            new=AsyncMock(side_effect=RuntimeError("https://secret.example/?token=abc")),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {"feature": "shard", "parameters": {"hero": "滑板鞋"}},
            )
        body = decode(response)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(body["ok"])
        self.assertTrue(body["retry"]["allowed"])
        self.assertEqual(body["retry"]["after_seconds"], 30)
        self.assertNotIn("secret.example", str(body))
        self.assertNotIn("token=abc", str(body))

    async def test_no_declared_delivery_capability_returns_406(self):
        with patch(
            "routers.groupguard_delivery.get_lolban_result",
            new=AsyncMock(
                return_value=(
                    {
                        "msg": "此账号状态正常",
                        "data": {
                            "qq": "2621735529",
                            "status": "正常",
                            "end_time": "账号状态正常",
                        },
                        "source": "live",
                    },
                    "live",
                    60,
                )
            ),
        ):
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "lolban",
                    "parameters": {"qq": "2621735529"},
                    "capabilities": {"text": False, "image": False, "forward": False},
                },
            )
        body = decode(response)
        self.assertEqual(response.status_code, 406)
        self.assertFalse(body["ok"])
        self.assertFalse(body["retry"]["allowed"])


if __name__ == "__main__":
    unittest.main()
