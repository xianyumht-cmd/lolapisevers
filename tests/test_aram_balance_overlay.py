import io
import unittest
from unittest.mock import patch

from fastapi.responses import Response
from PIL import Image

from renderers.aram_balance_overlay import build_aram_augment_image_with_balance
from renderers.aram_augments_rich_image import (
    ARAM_IMAGE_MAX_BYTES,
    ARAM_IMAGE_MAX_HEIGHT,
    ARAM_IMAGE_WIDTH,
)


def base_png(width=ARAM_IMAGE_WIDTH, height=800):
    image = Image.new("RGB", (width, height), (12, 17, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class AramBalanceOverlayTests(unittest.TestCase):
    def test_balance_panel_increases_height_and_keeps_png(self):
        body = base_png()
        payload = {
            "balance": {
                "status": "ok",
                "patch": "26.15",
                "current_patch_verified": True,
                "stale": False,
                "changes": [
                    {
                        "key": "damage_dealt",
                        "label": "造成伤害",
                        "value": "105%",
                        "direction": "buff",
                    },
                    {
                        "key": "damage_taken",
                        "label": "承受伤害",
                        "value": "110%",
                        "direction": "debuff",
                    },
                ],
                "base": {
                    "status": "ok",
                    "provider": "opgg",
                    "scope": "aram_base",
                    "patch": "16.15",
                    "display_patch": "26.15",
                    "current_patch_verified": True,
                    "complete": True,
                    "changes": [
                        {
                            "key": "healing",
                            "label": "治疗",
                            "value": "-20%",
                            "direction": "debuff",
                        },
                        {
                            "key": "shielding",
                            "label": "护盾",
                            "value": "-20%",
                            "direction": "debuff",
                        },
                    ],
                },
            }
        }

        with patch(
            "renderers.aram_balance_overlay.build_aram_augment_image_response",
            return_value=Response(content=body, media_type="image/png"),
        ):
            result = build_aram_augment_image_with_balance(object(), payload)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.media_type, "image/png")
        self.assertLessEqual(len(result.body), ARAM_IMAGE_MAX_BYTES)
        image = Image.open(io.BytesIO(bytes(result.body)))
        self.assertEqual(image.width, ARAM_IMAGE_WIDTH)
        self.assertGreater(image.height, 900)
        self.assertLessEqual(image.height, ARAM_IMAGE_MAX_HEIGHT)

    def test_syncing_patch_still_renders_panel_without_old_values(self):
        body = base_png()
        payload = {
            "balance": {
                "status": "syncing",
                "patch": "26.15",
                "page_patch": "26.14",
                "current_patch_verified": True,
                "stale": False,
                "changes": [],
                "base": {
                    "status": "syncing",
                    "provider": "opgg",
                    "scope": "aram_base",
                    "patch": "16.14",
                    "display_patch": "26.14",
                    "current_patch_verified": True,
                    "complete": False,
                    "changes": [],
                },
            }
        }

        with patch(
            "renderers.aram_balance_overlay.build_aram_augment_image_response",
            return_value=Response(content=body, media_type="image/png"),
        ):
            result = build_aram_augment_image_with_balance(object(), payload)

        self.assertEqual(result.status_code, 200)
        image = Image.open(io.BytesIO(bytes(result.body)))
        self.assertEqual(image.width, ARAM_IMAGE_WIDTH)
        self.assertGreater(image.height, 900)
        self.assertLessEqual(image.height, ARAM_IMAGE_MAX_HEIGHT)

    def test_unavailable_balance_returns_original_image(self):
        body = base_png()
        payload = {
            "balance": {
                "status": "unavailable",
                "changes": [],
                "base": {
                    "status": "unavailable",
                    "changes": [],
                },
            }
        }

        with patch(
            "renderers.aram_balance_overlay.build_aram_augment_image_response",
            return_value=Response(content=body, media_type="image/png"),
        ):
            result = build_aram_augment_image_with_balance(object(), payload)

        self.assertEqual(bytes(result.body), body)


if __name__ == "__main__":
    unittest.main()
