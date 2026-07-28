import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from cache import TTLCache
from services import aram_augments_service
from services.aram_augments_service import build_aram_augment_payload, query_aram_augments
from services.opgg_client import opgg_request
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


def payload_for(query):
    return {
        "hero": {"alias": "Ahri", "name": "阿狸"},
        "query": query,
        "rows": [{"name": "强化一"}],
        "item_builds": [],
        "starter_items": [],
        "boots": [],
        "summoner_spells": [],
        "skill_order": [],
        "total": 1,
        "source": "opgg",
        "source_url": "https://op.gg/ahri",
        "updated_at": "2026-07-26 12:00:00",
        "cache_expires_in": 120,
        "timing": {
            "cache_hit": False,
            "augment_ms": 10.0,
            "build_ms": 5.0,
            "build_status": "ok",
            "upstream_total_ms": 10.0,
        },
    }


def missing_snapshot(source_id="aram-mayhem-ahri"):
    return SnapshotLoadResult(
        ok=False,
        status="missing",
        source_id=source_id,
    )


class AramAugmentQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_canonical_alias_before_cache_and_returns_deep_copy(self):
        ctx = FakeContext()
        calls = []

        def fake_build(_ctx, query, *, resolved_hero=None):
            calls.append((query, resolved_hero["alias"]))
            return payload_for(query)

        with patch.object(
            aram_augments_service,
            "build_aram_augment_payload",
            side_effect=fake_build,
        ):
            first = await query_aram_augments(ctx, hero="阿狸")
            first["rows"][0]["name"] = "被调用方修改"
            second = await query_aram_augments(ctx, hero="Ahri")

        self.assertEqual(calls, [("阿狸", "Ahri")])
        self.assertEqual(second["rows"][0]["name"], "强化一")
        self.assertEqual(second["query"], "Ahri")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(second["cache_origin"], "opgg")
        self.assertTrue(second["timing"]["cache_hit"])
        self.assertTrue(ctx.aram_augment_cache.contains("aram_augments:ahri"))
        self.assertFalse(ctx.aram_augment_cache.contains("aram_augments:阿狸"))

    async def test_concurrent_aliases_share_one_canonical_flight(self):
        ctx = FakeContext()
        call_count = 0
        call_lock = threading.Lock()

        def fake_build(_ctx, query, *, resolved_hero=None):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.05)
            return payload_for(query)

        with patch.object(
            aram_augments_service,
            "build_aram_augment_payload",
            side_effect=fake_build,
        ):
            chinese, alias = await asyncio.gather(
                query_aram_augments(ctx, hero="阿狸"),
                query_aram_augments(ctx, hero="Ahri"),
            )

        self.assertEqual(call_count, 1)
        self.assertEqual({chinese["query"], alias["query"]}, {"阿狸", "Ahri"})
        self.assertTrue(
            chinese["timing"]["singleflight_shared"]
            or alias["timing"]["singleflight_shared"]
        )
        chinese["hero"]["name"] = "被修改"
        self.assertEqual(alias["hero"]["name"], "阿狸")


class AramAugmentPayloadTests(unittest.TestCase):
    def test_required_and_optional_pages_are_fetched_in_parallel(self):
        ctx = FakeContext()
        barrier = threading.Barrier(2, timeout=1)

        def fake_request(_ctx, **kwargs):
            barrier.wait()
            page = "build" if kwargs["page_kind"] == "build" else "augments"
            return UpstreamResponse(
                True,
                f"opgg-{page}",
                "ok",
                status_code=200,
                attempts=1,
                text=page,
            )

        with (
            patch.object(
                aram_augments_service,
                "request_opgg_html",
                side_effect=fake_request,
            ),
            patch.object(
                aram_augments_service,
                "load_aram_payload_snapshot",
                return_value=missing_snapshot(),
            ),
            patch.object(
                aram_augments_service,
                "save_aram_payload_snapshot",
                return_value=("", ""),
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_augments",
                return_value=[{"name": "强化一"}],
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_core_builds",
                return_value=[{"items": []}],
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_item_rows",
                return_value=[],
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_summoner_spells",
                return_value=[],
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_skill_order",
                return_value=[],
            ),
        ):
            result = build_aram_augment_payload(ctx, "阿狸")

        self.assertEqual(result["rows"], [{"name": "强化一"}])
        self.assertEqual(result["timing"]["build_status"], "ok")
        self.assertIn("upstream_total_ms", result["timing"])
        self.assertEqual(result["source"], "opgg")
        self.assertFalse(result["stale"])

    def test_optional_build_failure_does_not_hide_augment_data(self):
        ctx = FakeContext()

        def fake_request(_ctx, **kwargs):
            if kwargs["page_kind"] == "build":
                return UpstreamResponse(
                    False,
                    "opgg-build-ahri",
                    "failed",
                    attempts=1,
                    error=UpstreamError("read_timeout", "timeout", True),
                )
            return UpstreamResponse(
                True,
                "opgg-augments-ahri",
                "ok",
                status_code=200,
                attempts=1,
                text="augments",
            )

        with (
            patch.object(
                aram_augments_service,
                "request_opgg_html",
                side_effect=fake_request,
            ),
            patch.object(
                aram_augments_service,
                "load_aram_payload_snapshot",
                return_value=missing_snapshot(),
            ),
            patch.object(
                aram_augments_service,
                "save_aram_payload_snapshot",
                return_value=("", ""),
            ),
            patch.object(
                aram_augments_service,
                "extract_opgg_augments",
                return_value=[{"name": "强化一"}],
            ),
        ):
            result = build_aram_augment_payload(ctx, "阿狸")

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["item_builds"], [])
        self.assertEqual(result["timing"]["build_status"], "unavailable")
        self.assertEqual(
            result["timing"]["build_error_class"],
            "read_timeout",
        )


class OpggClientTests(unittest.TestCase):
    @patch("services.opgg_client.requests.get")
    def test_retries_with_bounded_tuple_timeouts(self, get_mock):
        get_mock.side_effect = [
            requests.Timeout("first timeout"),
            SimpleNamespace(status_code=200),
        ]

        response = opgg_request("https://op.gg/example")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_mock.call_count, 2)
        for call in get_mock.call_args_list:
            self.assertEqual(call.kwargs["timeout"], (3.0, 7.0))

    @patch("services.opgg_client.requests.get")
    def test_attempt_count_is_capped(self, get_mock):
        get_mock.side_effect = requests.Timeout("always")

        with self.assertRaises(requests.Timeout):
            opgg_request("https://op.gg/example", attempts=99)

        self.assertEqual(get_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
