import threading
import unittest
from unittest.mock import patch

from fastapi.responses import Response

from cache import TTLCache
from routers.aram_augments import _build_cached_image_response
from services.aram_balance_service import _slug_candidates


class FakeContext:
    def __init__(self):
        self.aram_augment_cache = TTLCache(ttl_seconds=120)
        self.aram_image_cache_seconds = 300
        self._locks = {}

    def aram_image_lock(self, key):
        if key not in self._locks:
            self._locks[key] = threading.Lock()
        return self._locks[key]


class AramBalanceSlugTests(unittest.TestCase):
    def test_multi_word_alias_adds_hyphenated_candidate(self):
        candidates = _slug_candidates(
            {"alias": "MasterYi", "slug": "masteryi"}
        )
        self.assertIn("master-yi", candidates)

    def test_monkeyking_prefers_wukong(self):
        candidates = _slug_candidates(
            {"alias": "MonkeyKing", "slug": "monkeyking"}
        )
        self.assertEqual(candidates[0], "wukong")


class AramBalanceDeliveryTests(unittest.TestCase):
    def test_cached_image_builder_enriches_payload_for_groupguard_path(self):
        ctx = FakeContext()
        payload = {
            "hero": {"alias": "Ahri", "name": "阿狸"},
            "rows": [{"name": "强化一"}],
            "item_builds": [],
            "starter_items": [],
            "boots": [],
            "summoner_spells": [],
            "skill_order": [],
            "total": 1,
        }
        balance = {
            "status": "ok",
            "provider": "arammayhem",
            "patch": "16.15",
            "changes": [
                {
                    "key": "damage_dealt",
                    "label": "造成伤害",
                    "value": "105%",
                    "direction": "buff",
                }
            ],
            "summary": "造成伤害 105%",
            "stale": False,
            "snapshot_age_seconds": 0,
            "error_class": "",
        }
        captured = {}

        def fake_render(_ctx, enriched):
            captured.update(enriched)
            return Response(content=b"fake-png", media_type="image/png")

        with (
            patch(
                "routers.aram_augments.query_aram_balance",
                return_value=balance,
            ) as balance_mock,
            patch(
                "routers.aram_augments.build_aram_augment_image_with_balance",
                side_effect=fake_render,
            ),
        ):
            response = _build_cached_image_response(ctx, payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(captured["balance"]["patch"], "16.15")
        balance_mock.assert_called_once_with(ctx, "Ahri")


if __name__ == "__main__":
    unittest.main()
