import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cache import TTLCache
from services.aram_balance_service import (
    _riot_display_patch,
    parse_balance_page,
    query_aram_balance,
)
from services.persistent_snapshot_store import SnapshotLoadResult
from services.upstream_http_client import UpstreamError, UpstreamResponse


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
                    "alias": "Ahri",
                    "slug": "ahri",
                    "name": "阿狸",
                    "title": "九尾妖狐",
                    "keywords": "狐狸",
                    "heroId": "103",
                }
            ],
        )
        self.aram_augment_cache.set(
            "aram_current_riot_patch",
            {"patch": "16.15"},
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


class BalanceParserTests(unittest.TestCase):
    def test_parses_patch_values_and_buff_debuff_direction(self):
        result = parse_balance_page(
            """
            <html><body>
            Patch: 16.15
            Damage Dealt 105%
            Damage Taken 90%
            Ability Haste +20
            Healing 90%
            </body></html>
            """
        )

        self.assertEqual(result["patch"], "16.15")
        by_key = {item["key"]: item for item in result["changes"]}
        self.assertEqual(by_key["damage_dealt"]["direction"], "buff")
        self.assertEqual(by_key["damage_taken"]["direction"], "buff")
        self.assertEqual(by_key["ability_haste"]["direction"], "buff")
        self.assertEqual(by_key["healing"]["direction"], "debuff")
        self.assertIn("造成伤害 105%", result["summary"])

    def test_parses_compact_negative_modifiers_from_live_page_shape(self):
        result = parse_balance_page(
            "Patch: 26.14 ↓Damage Dealt-5% ↓Healing-10%"
        )

        self.assertEqual(result["patch"], "26.14")
        by_key = {item["key"]: item for item in result["changes"]}
        self.assertEqual(by_key["damage_dealt"]["value"], "-5%")
        self.assertEqual(by_key["damage_dealt"]["direction"], "debuff")
        self.assertEqual(by_key["healing"]["value"], "-10%")
        self.assertEqual(by_key["healing"]["direction"], "debuff")

    def test_damage_taken_positive_adjustment_is_debuff(self):
        result = parse_balance_page("Patch: 16.15 Damage Taken +10%")
        self.assertEqual(result["changes"][0]["direction"], "debuff")

    def test_ddragon_version_maps_to_public_patch_label(self):
        self.assertEqual(_riot_display_patch("16.15.1"), "26.15")
        self.assertEqual(_riot_display_patch("16.14.1"), "26.14")


class BalanceQueryTests(unittest.TestCase):
    def test_live_result_is_cached_and_persisted(self):
        ctx = FakeContext()
        response = UpstreamResponse(
            True,
            "aram-balance-page",
            "ok",
            status_code=200,
            attempts=1,
            text="Patch: 16.15 Damage Dealt 105% Damage Taken 110%",
        )
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-balance-ahri")
        )
        client = FakeClient(response)

        with (
            patch("services.aram_balance_service.snapshot_store", return_value=store),
            patch("services.aram_balance_service.upstream_client", return_value=client),
        ):
            first = query_aram_balance(ctx, "阿狸")
            second = query_aram_balance(ctx, "Ahri")

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["patch"], "16.15")
        self.assertTrue(first["current_patch_verified"])
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(
            {item["direction"] for item in first["changes"]},
            {"buff", "debuff"},
        )

    def test_patch_mismatch_hides_old_balance_values(self):
        ctx = FakeContext()
        response = UpstreamResponse(
            True,
            "aram-balance-page",
            "ok",
            status_code=200,
            attempts=1,
            text="Patch: 16.14 Damage Dealt 105% Healing 90%",
        )
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-balance-ahri")
        )
        client = FakeClient(response)

        with (
            patch("services.aram_balance_service.snapshot_store", return_value=store),
            patch("services.aram_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_balance(ctx, "阿狸")

        self.assertEqual(result["status"], "syncing")
        self.assertEqual(result["patch"], "16.15")
        self.assertEqual(result["page_patch"], "16.14")
        self.assertTrue(result["current_patch_verified"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["error_class"], "patch_mismatch")
        self.assertEqual(store.saved, [])

    def test_upstream_failure_uses_current_persistent_snapshot(self):
        ctx = FakeContext()
        snapshot_payload = {
            "status": "ok",
            "provider": "arammayhem",
            "patch": "16.15",
            "page_patch": "16.15",
            "current_patch_verified": True,
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
            "duration_ms": 10.0,
            "attempts": 1,
            "http_status": 200,
        }
        store = FakeStore(
            SnapshotLoadResult(
                True,
                "fresh",
                "aram-balance-ahri",
                payload=snapshot_payload,
                age_seconds=60,
            )
        )
        client = FakeClient(
            UpstreamResponse(
                False,
                "aram-balance-page",
                "failed",
                attempts=1,
                error=UpstreamError("read_timeout", "timeout", True),
            )
        )

        with (
            patch("services.aram_balance_service.snapshot_store", return_value=store),
            patch("services.aram_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_balance(ctx, "阿狸")

        self.assertEqual(result["status"], "snapshot")
        self.assertTrue(result["stale"])
        self.assertEqual(result["snapshot_age_seconds"], 60)
        self.assertEqual(result["patch"], "16.15")
        self.assertTrue(result["current_patch_verified"])
        self.assertEqual(result["error_class"], "read_timeout")

    def test_outdated_snapshot_is_hidden_after_patch_transition(self):
        ctx = FakeContext()
        snapshot_payload = {
            "status": "ok",
            "provider": "arammayhem",
            "patch": "16.14",
            "changes": [
                {
                    "key": "healing",
                    "label": "治疗",
                    "value": "90%",
                    "direction": "debuff",
                }
            ],
            "summary": "治疗 90%",
            "stale": False,
            "snapshot_age_seconds": 0,
            "error_class": "",
        }
        store = FakeStore(
            SnapshotLoadResult(
                True,
                "fresh",
                "aram-balance-ahri",
                payload=snapshot_payload,
                age_seconds=60,
            )
        )
        client = FakeClient(
            UpstreamResponse(
                False,
                "aram-balance-page",
                "failed",
                attempts=1,
                error=UpstreamError("read_timeout", "timeout", True),
            )
        )

        with (
            patch("services.aram_balance_service.snapshot_store", return_value=store),
            patch("services.aram_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_balance(ctx, "阿狸")

        self.assertEqual(result["status"], "syncing")
        self.assertEqual(result["patch"], "16.15")
        self.assertEqual(result["page_patch"], "16.14")
        self.assertEqual(result["changes"], [])

    def test_no_snapshot_returns_optional_unavailable_result(self):
        ctx = FakeContext()
        store = FakeStore(
            SnapshotLoadResult(False, "missing", "aram-balance-ahri")
        )
        client = FakeClient(
            UpstreamResponse(
                False,
                "aram-balance-page",
                "failed",
                attempts=1,
                error=UpstreamError("dns_error", "offline", True),
            )
        )

        with (
            patch("services.aram_balance_service.snapshot_store", return_value=store),
            patch("services.aram_balance_service.upstream_client", return_value=client),
        ):
            result = query_aram_balance(ctx, "阿狸")

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["error_class"], "dns_error")


if __name__ == "__main__":
    unittest.main()
