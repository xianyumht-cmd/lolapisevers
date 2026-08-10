import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routers.aram_augments import _aram_image_cache_key, _payload_with_balance


MAYHEM_BALANCE = {
    "status": "ok",
    "provider": "arammayhem",
    "patch": "26.15",
    "changes": [
        {
            "key": "damage_taken",
            "label": "承受伤害",
            "value": "+20%",
            "direction": "debuff",
        }
    ],
}

BASE_BALANCE = {
    "status": "ok",
    "provider": "opgg",
    "scope": "aram_base",
    "patch": "16.15",
    "display_patch": "26.15",
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
}


class AramBalanceLayerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace()
        self.payload = {
            "hero": {"alias": "Seraphine", "name": "萨勒芬妮"},
            "rows": [{"name": "测试强化", "performance": 0.6}],
            "total": 1,
        }

    def test_groupguard_image_entry_enriches_both_layers(self):
        with patch(
            "routers.aram_augments.query_aram_balance",
            return_value=MAYHEM_BALANCE,
        ) as mayhem_query, patch(
            "routers.aram_augments.query_aram_base_balance",
            return_value=BASE_BALANCE,
        ) as base_query:
            result = _payload_with_balance(self.ctx, self.payload)

        mayhem_query.assert_called_once_with(self.ctx, "Seraphine")
        base_query.assert_called_once_with(self.ctx, "Seraphine")
        self.assertEqual(result["balance"]["provider"], "arammayhem")
        self.assertEqual(result["balance"]["base"]["provider"], "opgg")
        self.assertEqual(result["balance"]["base"]["scope"], "aram_base")
        self.assertIn("治疗", result["balance"]["base"]["changes"][0]["label"])

    def test_existing_mayhem_result_only_fetches_missing_base_layer(self):
        payload = {**self.payload, "balance": MAYHEM_BALANCE}
        with patch(
            "routers.aram_augments.query_aram_balance",
            return_value=MAYHEM_BALANCE,
        ) as mayhem_query, patch(
            "routers.aram_augments.query_aram_base_balance",
            return_value=BASE_BALANCE,
        ) as base_query:
            result = _payload_with_balance(self.ctx, payload)

        mayhem_query.assert_not_called()
        base_query.assert_called_once_with(self.ctx, "Seraphine")
        self.assertEqual(result["balance"]["base"]["summary"] if "summary" in result["balance"]["base"] else "", "")

    def test_base_balance_change_invalidates_image_etag(self):
        first = {
            **self.payload,
            "balance": {**MAYHEM_BALANCE, "base": BASE_BALANCE},
        }
        changed_base = {
            **BASE_BALANCE,
            "changes": [
                {
                    "key": "healing",
                    "label": "治疗",
                    "value": "-10%",
                    "direction": "debuff",
                }
            ],
        }
        second = {
            **self.payload,
            "balance": {**MAYHEM_BALANCE, "base": changed_base},
        }

        _, first_etag = _aram_image_cache_key(first)
        _, second_etag = _aram_image_cache_key(second)
        self.assertNotEqual(first_etag, second_etag)


if __name__ == "__main__":
    unittest.main()
