import io
import unittest
from unittest.mock import patch

from fastapi.responses import Response
from PIL import Image

from renderers.aram_balance_overlay import build_aram_augment_image_with_balance


def base_png(width=900, height=800):
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
            }
        }

        with patch(
            "renderers.aram_balance_overlay.build_aram_augment_image_response",
            return_value=Response(content=body, media_type="image/png"),
        ):
            result = build_aram_augment_image_with_balance(object(), payload)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.media_type, "image/png")
        image = Image.open(io.BytesIO(bytes(result.body)))
        self.assertEqual(image.size, (900, 916))

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
            }
        }

        with patch(
            "renderers.aram_balance_overlay.build_aram_augment_image_response",
            return_value=Response(content=body, media_type="image/png"),
        ):
            result = build_aram_augment_image_with_balance(object(), payload)

        self.assertEqual(result.status_code, 200)
        image = Image.open(io.BytesIO(bytes(result.body)))
        self.assertEqual(image.size, (900, 916))

    def test_unavailable_balance_returns_original_image(self):
        body = base_png()
        payload = {
            "balance": {
                "status": "unavailable",
                "changes": [],
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
