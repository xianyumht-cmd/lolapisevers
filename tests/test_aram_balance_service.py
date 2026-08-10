import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cache import TTLCache
from services.aram_balance_service import (
    build_aram_balance_payload,
    extract_aram_balance_state,
)
from services.persistent_snapshot_store import PersistentSnapshotStore


SERAPHINE_HTML = """
<html><body>
<h1>Seraphine ARAM Build</h1>
<div>Patch 16.13</div>
<section>
Balance adjustment
Damage dealt -
Damage taken +20%
Attack speed -
Cooldown reduction -20
Healing -20%
Tenacity -
Shield amount -20%
</section>
<div>Build</div>
</body></html>
"""


class Context:
    def __init__(self, root):
        self.aram_augment_cache = TTLCache(ttl_seconds=120)
        self.upstream_snapshot_store = PersistentSnapshotStore(Path(root))


class AramBalanceParserTests(unittest.TestCase):
    def test_seraphine_returns_complete_non_neutral_state(self):
        result = extract_aram_balance_state(SERAPHINE_HTML)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["complete"])
        self.assertEqual(result["patch"], "16.13")
        self.assertEqual(
            [(item["key"], item["value"]) for item in result["items"]],
            [
                ("damage_taken", "+20%"),
                ("ability_haste", "-20"),
                ("healing", "-20%"),
                ("shielding", "-20%"),
            ],
        )
        self.assertTrue(all(item["direction"] == "debuff" for item in result["items"]))
        self.assertIn("治疗 -20%", result["summary"])
        self.assertIn("护盾 -20%", result["summary"])

    def test_direction_understands_inverse_damage_taken(self):
        html = """
        Balance adjustment
        Damage dealt +5%
        Damage taken -10%
        Healing +10%
        Summoner spells
        """
        result = extract_aram_balance_state(html)
        directions = {item["key"]: item["direction"] for item in result["items"]}
        self.assertEqual(directions["damage_dealt"], "buff")
        self.assertEqual(directions["damage_taken"], "buff")
        self.assertEqual(directions["healing"], "buff")

    def test_all_neutral_values_are_a_real_none_state(self):
        html = """
        Balance adjustment
        Damage dealt -
        Damage taken -
        Attack speed -
        Cooldown reduction -
        Healing -
        Shield amount -
        Summoner spells
        """
        result = extract_aram_balance_state(html)
        self.assertEqual(result["status"], "none")
        self.assertTrue(result["complete"])
        self.assertEqual(result["items"], [])

    def test_missing_balance_section_is_not_reported_as_none(self):
        result = extract_aram_balance_state("Seraphine Build without balance data")
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["complete"])
        self.assertEqual(result["error_class"], "balance_section_missing")


class AramBalanceFallbackTests(unittest.TestCase):
    def test_live_state_is_persisted_then_reused_as_snapshot(self):
        champion = {
            "alias": "Seraphine",
            "slug": "seraphine",
            "name": "萨勒芬妮",
        }
        ok_response = SimpleNamespace(
            ok=True,
            text=SERAPHINE_HTML,
            status_code=200,
            status="ok",
        )
        failed_response = SimpleNamespace(
            ok=False,
            text="",
            status_code=0,
            status="failed",
            error=SimpleNamespace(
                error_class="read_timeout",
                message="timeout",
            ),
        )

        with tempfile.TemporaryDirectory() as temp:
            first = Context(temp)
            with patch(
                "services.aram_balance_service.request_opgg_html",
                return_value=ok_response,
            ):
                live = build_aram_balance_payload(
                    first,
                    "萨勒芬妮",
                    resolved_hero=champion,
                )
            self.assertEqual(live["status"], "ok")
            self.assertFalse(live["stale"])

            restarted = Context(temp)
            with patch(
                "services.aram_balance_service.request_opgg_html",
                return_value=failed_response,
            ):
                fallback = build_aram_balance_payload(
                    restarted,
                    "萨勒芬妮",
                    resolved_hero=champion,
                )
            self.assertEqual(fallback["status"], "snapshot")
            self.assertTrue(fallback["stale"])
            self.assertEqual(fallback["fallback_reason"], "read_timeout")
            self.assertIn("治疗 -20%", fallback["summary"])

    def test_upstream_failure_without_snapshot_does_not_claim_no_adjustment(self):
        champion = {
            "alias": "Seraphine",
            "slug": "seraphine",
            "name": "萨勒芬妮",
        }
        failed_response = SimpleNamespace(
            ok=False,
            text="",
            status_code=0,
            status="failed",
            error=SimpleNamespace(
                error_class="read_timeout",
                message="timeout",
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(temp)
            with patch(
                "services.aram_balance_service.request_opgg_html",
                return_value=failed_response,
            ):
                result = build_aram_balance_payload(
                    ctx,
                    "萨勒芬妮",
                    resolved_hero=champion,
                )
            self.assertEqual(result["status"], "unavailable")
            self.assertIn("不等于无修正", result["summary"])


if __name__ == "__main__":
    unittest.main()
