import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cache import TTLCache
from services.aram_base_balance_service import (
    parse_base_balance_page,
    query_aram_base_balance,
)
from services.persistent_snapshot_store import SnapshotLoadResult
from services.upstream_http_client import UpstreamError, UpstreamResponse


SERAPHINE_HTML = """
<html><body>
<div>Patch 16.15</div>
<section>
Balance adjustment
Damage Dealt -
Damage Taken +20%
Attack Speed -
Cooldown Reduction -20
Healing -20%
Tenacity -
Shield Amount -20%
Energy Regen -
</section>
<div>Build</div>
</body></html>
"""

SERAPHINE_ZH_HTML = """
<html><body>
<div>16.15 版本</div>
<section>
平衡调整
造成伤害 -
承伤 +20%
攻速 -
技能加速 -20
生命恢复 -20%
韧性 -
护盾吸收量 -20%
法力回复 -
</section>
<div>出装</div>
</body></html>
"""


class FakeContext:
    def __init__(self):
        self.config = SimpleNamespace(
            aram_augment_cache_seconds=120,
            shard_hero_url="https://example.invalid/heroes.json",
        )
        self.aram_augment_cache = TTLCache(ttl_seconds=120)
        self.aram_augment_cache.set(
            "champions",
            [
                {
                    "alias": "Seraphine",
                    "slug": "seraphine",
                    "name": "萨勒芬妮",
                    "title": "星籁歌姬",
                    "keywords": "萨勒芬妮",
                    "heroId": "147",
                }
            ],
        )
        self.aram_augment_cache.set(
            "aram_current_riot_patch",
            {"patch": "26.15"},
        )


class FakeStore:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.saved = []
        self.errors = []

    def load(self, source_id, max_age_seconds):
        return self.snapshot

    def save(self, source_id, payload, metadata):
        self.saved.append((source_id, payload, metadata))
        return {"captured_at": "2026-08-11T00:00:00+00:00"}

    def record_refresh_error(self, source_id, error_class, message=""):
        self.errors.append((source_id, error_class, message))


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, source_id, url, **kwargs):
        self.calls.append((source_id, url, kwargs))
        return self.response


class BaseBalanceParserTests(unittest.TestCase):
    def assert_seraphine_complete(self, result):
        self.assertTrue(result["complete"])
        self.assertEqual(result["patch"], "16.15")
        self.assertEqual(
            [(item["key"], item["value"]) for item in result["changes"]],
            [
                ("damage_taken", "+20%"),
                ("ability_haste", "-20"),
                ("healing", "-20%"),
                ("shielding", "-20%"),
            ],
        )
        self.assertTrue(
            all(item["direction"] == "debuff" for item in result["changes"])
        )
        self.assertIn("治疗 -20%", result["summary"])
        self.assertIn("护盾 -20%", result["summary"])

    def test_seraphine_complete_base_state(self):
        self.assert_seraphine_complete(parse_base_balance_page(SERAPHINE_HTML))

    def test_current_chinese_opgg_labels_are_supported(self):
        self.assert_seraphine_complete(parse_base_balance_page(SERAPHINE_ZH_HTML))

    def test_damage_taken_negative_is_buff(self):
        result = parse_base_balance_page(
            "Balance adjustment Damage Dealt +5% Damage Taken -10% Healing +10% Build"
        )
        directions = {item["key"]: item["direction"] for item in result["changes"]}
        self.assertEqual(directions["damage_dealt"], "buff")
        self.assertEqual(directions["damage_taken"], "buff")
        self.assertEqual(directions["healing"], "buff")

    def test_all_neutral_values_are_complete(self):
        result = parse_base_balance_page(
            """
            Balance adjustment
            Damage Dealt - Damage Taken - Attack Speed - Cooldown Reduction -
            Healing - Shield Amount - Tenacity - Energy Regen -
            Summoner Spells
            """
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["changes"], [])
        self.assertIn("无英雄专属基础平衡修正", result["summary"])

    def test_unknown_numeric_modifier_rejects_partial_state(self):
        result = parse_base_balance_page(
            "Balance adjustment Damage Dealt - Future Modifier -15% Summoner Spells"
        )
        self.assertFalse(result["complete"])
        self.assertEqual(result["error_class"], "unparsed_balance_values")

    def test_missing_section_is_unavailable_not_none(self):
        result = parse_base_balance_page("Seraphine build without balance section")
        self.assertFalse(result["complete"])
        self.assertEqual(result["error_class"], "balance_section_missing")


class BaseBalanceQueryTests(unittest.TestCase):
    def test_live_complete_state_is_cached_and_persisted(self):
        ctx = FakeContext()
        response = UpstreamResponse(
            True,
            "aram-base-balance-page",
            "ok",
            status_code=200,
            attempts=1,
            text=SERAPHINE_HTML,
        )
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-base-balance-seraphine")
        )
        client = FakeClient(response)

        with (
            patch("services.aram_base_balance_service.snapshot_store", return_value=store),
            patch("services.aram_base_balance_service.upstream_client", return_value=client),
        ):
            first = query_aram_base_balance(ctx, "萨勒芬妮")
            second = query_aram_base_balance(ctx, "Seraphine")

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["scope"], "aram_base")
        self.assertEqual(first["patch"], "16.15")
        self.assertEqual(first["display_patch"], "26.15")
        self.assertTrue(first["current_patch_verified"])
        self.assertTrue(first["complete"])
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0][1],
            "https://op.gg/lol/modes/aram/seraphine/build",
        )
        self.assertEqual(len(store.saved), 1)

    def test_patch_mismatch_hides_old_complete_values(self):
        ctx = FakeContext()
        response = UpstreamResponse(
            True,
            "aram-base-balance-page",
            "ok",
            status_code=200,
            attempts=1,
            text=SERAPHINE_HTML.replace("16.15", "16.14"),
        )
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-base-balance-seraphine")
        )
        client = FakeClient(response)

        with (
            patch("services.aram_base_balance_service.snapshot_store", return_value=store),
            patch("services.aram_base_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_base_balance(ctx, "萨勒芬妮")

        self.assertEqual(result["status"], "syncing")
        self.assertEqual(result["patch"], "16.14")
        self.assertEqual(result["display_patch"], "26.14")
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["error_class"], "patch_mismatch")
        self.assertEqual(store.saved, [])

    def test_upstream_failure_reuses_current_complete_snapshot(self):
        ctx = FakeContext()
        snapshot_payload = {
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
                }
            ],
            "summary": "治疗 -20%",
            "stale": False,
            "snapshot_age_seconds": 0,
            "error_class": "",
        }
        store = FakeStore(
            SnapshotLoadResult(
                True,
                "fresh",
                "aram-base-balance-seraphine",
                payload=snapshot_payload,
                age_seconds=60,
            )
        )
        client = FakeClient(
            UpstreamResponse(
                False,
                "aram-base-balance-page",
                "failed",
                attempts=1,
                error=UpstreamError("read_timeout", "timeout", True),
            )
        )

        with (
            patch("services.aram_base_balance_service.snapshot_store", return_value=store),
            patch("services.aram_base_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_base_balance(ctx, "萨勒芬妮")

        self.assertEqual(result["status"], "snapshot")
        self.assertTrue(result["stale"])
        self.assertEqual(result["snapshot_age_seconds"], 60)
        self.assertIn("治疗 -20%", result["summary"])

    def test_failure_without_snapshot_never_claims_no_adjustment(self):
        ctx = FakeContext()
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-base-balance-seraphine")
        )
        client = FakeClient(
            UpstreamResponse(
                False,
                "aram-base-balance-page",
                "failed",
                attempts=1,
                error=UpstreamError("dns_error", "offline", True),
            )
        )

        with (
            patch("services.aram_base_balance_service.snapshot_store", return_value=store),
            patch("services.aram_base_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_base_balance(ctx, "萨勒芬妮")

        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["complete"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["error_class"], "dns_error")


if __name__ == "__main__":
    unittest.main()
