import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.responses import Response

from routers.groupguard_delivery import groupguard_query


def request_with_ctx():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=object())),
        headers={},
    )


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


CASES = (
    ("lolban", {"qq": "123456789"}),
    ("scammer", {"identifier_type": "qq", "identifier": "123456789"}),
    ("peer", {"identifier_type": "qq", "identifier": "123456789"}),
    ("dynamic", {"command_id": "demo.query", "keyword": "test"}),
)


class FourQueryThreeModeTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, feature, parameters, preferred, renderer=None):
        payload = {
            "qq": "123456789",
            "source": "live",
            "status": "safe",
            "count": 1,
        }
        lolban_service = SimpleNamespace(
            get_result=AsyncMock(return_value=(payload, "live", 60))
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.get_lolban_service",
                    return_value=lolban_service,
                )
            )
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.query_contact_risk",
                    new=AsyncMock(return_value=payload),
                )
            )
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.query_dynamic",
                    new=AsyncMock(return_value=payload),
                )
            )
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.format_lolban_text",
                    return_value=f"{feature} final text",
                )
            )
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.format_contact_risk_text",
                    return_value=f"{feature} final text",
                )
            )
            stack.enter_context(
                patch(
                    "routers.groupguard_delivery.format_dynamic_text",
                    return_value=f"{feature} final text",
                )
            )
            if renderer is not None:
                stack.enter_context(
                    patch(
                        "routers.groupguard_delivery.build_query_text_card_response",
                        return_value=renderer,
                    )
                )
            return await groupguard_query(
                request_with_ctx(),
                {
                    "feature": feature,
                    "parameters": parameters,
                    "preferred": preferred,
                    "capabilities": {
                        "text": True,
                        "image": True,
                        "forward": True,
                    },
                },
            )

    async def test_text_and_forward_for_all_four_queries(self):
        for feature, parameters in CASES:
            with self.subTest(feature=feature, mode="text"):
                body = decode(await self._call(feature, parameters, "text"))
                self.assertEqual(body["delivery"]["kind"], "segments")
                self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
            with self.subTest(feature=feature, mode="forward"):
                body = decode(await self._call(feature, parameters, "forward"))
                self.assertEqual(body["delivery"]["kind"], "forward")
                self.assertEqual(body["delivery"]["segments"][0]["type"], "forward")

    async def test_image_for_all_four_queries(self):
        png = b"\x89PNG\r\n\x1a\nquery-card"
        rendered = Response(content=png, media_type="image/png")
        for feature, parameters in CASES:
            with self.subTest(feature=feature):
                body = decode(
                    await self._call(feature, parameters, "image", renderer=rendered)
                )
                self.assertEqual(body["delivery"]["kind"], "segments")
                self.assertEqual(body["delivery"]["segments"][0]["type"], "image")

    async def test_image_render_failure_falls_back_to_text(self):
        rendered = Response(content=b"", media_type="image/png", status_code=503)
        body = decode(
            await self._call(
                "lolban",
                {"qq": "123456789"},
                "image",
                renderer=rendered,
            )
        )
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertEqual(body["meta"]["delivery_fallback"], "image_render_failed")


if __name__ == "__main__":
    unittest.main()
