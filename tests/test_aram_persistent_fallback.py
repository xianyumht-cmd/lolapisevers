import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cache import TTLCache
from fastapi import HTTPException
from services import aram_augments_service
from services.aram_augments_service import (
    AramRequiredUpstreamError,
    build_aram_augment_payload,
    query_aram_augments,
)
from services.aram_upstream_state import (
    HERO_CATALOG_SOURCE_ID,
    aram_payload_source_id,
    load_champion_catalog,
)
from services.persistent_snapshot_store import PersistentSnapshotStore
from services.upstream_http_client import UpstreamError, UpstreamResponse


HERO_DATA = {
    "hero": [
        {
            "alias": "Ahri",
            "name": "阿狸",
            "title": "九尾妖狐",
            "keywords": "狐狸",
            "heroId": "103",
        }
    ]
}
CHAMPION = {
    "alias": "Ahri",
    "slug": "ahri",
    "name": "阿狸",
    "title": "九尾妖狐",
    "keywords": "狐狸",
    "heroId": "103",
}


def live_payload():
    return {
        "hero": dict(CHAMPION),
        "query": "阿狸",
        "rows": [{"name": "强化一"}],
        "item_builds": [{"items": [{"id": "1001"}]}],
        "starter_items": [{"items": [{"id": "2001"}]}],
        "boots": [{"items": [{"id": "3001"}]}],
        "summoner_spells": [{"name": "闪现"}],
        "skill_order": ["Q", "W", "E"],
        "total": 1,
        "source": "opgg",
        "provider": "opgg",
        "source_url": "https://op.gg/zh-cn/lol/modes/aram-mayhem/ahri/augments",
        "updated_at": "2026-07-28 12:00:00",
        "stale": False,
        "snapshot_age_seconds": 0,
        "fallback_reason": "",
        "lookup_source": "live",
        "lookup_snapshot_age_seconds": 0,
        "cache_expires_in": 120,
        "timing": {
            "cache_hit": False,
            "fallback": False,
            "augment_ms": 10.0,
            "build_ms": 5.0,
            "build_status": "ok",
            "upstream_total_ms": 15.0,
        },
    }


class FakeClient:
    def __init__(self, json_responses=None):
        self.json_responses = list(json_responses or [])
        self.calls = []

    def get_json(self, source_id, url, **kwargs):
        self.calls.append((source_id, url, dict(kwargs)))
        if not self.json_responses:
            raise AssertionError("no queued JSON response")
        return self.json_responses.pop(0)

    def request(self, source_id, url, **kwargs):
        self.calls.append((source_id, url, dict(kwargs)))
        return UpstreamResponse(
            False,
            source_id,
            "failed",
            attempts=1,
            error=UpstreamError("read_timeout", "timeout", True),
        )


class FailingSaveStore(PersistentSnapshotStore):
    def save(self, source_id, payload, metadata=None, **kwargs):
        if source_id.startswith("aram-mayhem-"):
            raise OSError("disk full")
        return super().save(source_id, payload, metadata, **kwargs)


class Context:
    def __init__(self, root, client=None, store=None):
        self.config = SimpleNamespace(
            aram_augment_cache_seconds=120,
            shard_hero_url="https://example.invalid/heroes.json",
        )
        self.aram_augment_cache = TTLCache(ttl_seconds=120)
        self.upstream_http_client = client or FakeClient()
        self.upstream_snapshot_store = store or PersistentSnapshotStore(Path(root))
        self.logger = SimpleNamespace(
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        )

    def seed_champion(self):
        self.aram_augment_cache.set("champions", [dict(CHAMPION)])
        self.aram_augment_cache.set(
            "champion_catalog",
            {
                "champions": [dict(CHAMPION)],
                "mode": "live",
                "age_seconds": 0,
                "error_class": "",
                "snapshot_status": "hit",
            },
        )


def ok_json(data, *, status="ok", status_code=200, etag=""):
    return UpstreamResponse(
        True,
        HERO_CATALOG_SOURCE_ID,
        status,
        status_code=status_code,
        attempts=1,
        data=data,
        etag=etag,
    )


def failed_json(error_class="read_timeout", *, status="failed"):
    return UpstreamResponse(
        False,
        HERO_CATALOG_SOURCE_ID,
        status,
        attempts=2,
        error=UpstreamError(error_class, error_class, True),
        circuit_state="open" if status == "circuit_open" else "closed",
    )


class ChampionCatalogPersistenceTests(unittest.TestCase):
    def test_live_catalog_is_saved_and_restart_uses_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Context(
                temp,
                client=FakeClient([ok_json(HERO_DATA, etag='"hero-v1"')]),
            )
            live = load_champion_catalog(first)
            self.assertEqual(live["mode"], "live")
            self.assertEqual(live["champions"][0]["heroId"], "103")
            self.assertTrue(
                (Path(temp) / f"{HERO_CATALOG_SOURCE_ID}.json").is_file()
            )

            second = Context(
                temp,
                client=FakeClient([failed_json("dns_error")]),
            )
            restored = load_champion_catalog(second)
            self.assertEqual(restored["mode"], "stale")
            self.assertEqual(restored["error_class"], "dns_error")
            self.assertEqual(restored["champions"][0]["alias"], "Ahri")

    def test_conditional_304_preserves_catalog_body_and_etag(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save(
                HERO_CATALOG_SOURCE_ID,
                HERO_DATA,
                {"etag": '"hero-v1"'},
            )
            client = FakeClient(
                [
                    ok_json(
                        None,
                        status="not_modified",
                        status_code=304,
                    )
                ]
            )
            result = load_champion_catalog(
                Context(temp, client=client, store=store)
            )
            self.assertEqual(result["mode"], "live")
            self.assertTrue(result["conditional_not_modified"])
            self.assertEqual(client.calls[0][2]["etag"], '"hero-v1"')
            self.assertEqual(
                store.load(HERO_CATALOG_SOURCE_ID).metadata["etag"],
                '"hero-v1"',
            )


class AramPayloadPersistenceTests(unittest.TestCase):
    def test_live_payload_is_saved_then_restart_falls_back_to_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(temp)
            ctx.seed_champion()
            augment = {
                "rows": [{"name": "强化一"}],
                "source_url": "https://op.gg/ahri/augments",
                "duration_ms": 10.0,
                "attempts": 1,
                "http_status": 200,
            }
            optional = {
                "item_builds": [],
                "starter_items": [],
                "boots": [],
                "summoner_spells": [],
                "skill_order": [],
                "status": "ok",
                "error_class": "",
                "duration_ms": 5.0,
                "attempts": 1,
                "http_status": 200,
            }
            with (
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    return_value=augment,
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value=optional,
                ),
            ):
                first = asyncio.run(query_aram_augments(ctx, hero="阿狸"))
            self.assertEqual(first["source"], "opgg")
            source_id = aram_payload_source_id("Ahri")
            self.assertTrue((Path(temp) / f"{source_id}.json").is_file())

            restarted = Context(temp)
            restarted.seed_champion()
            with (
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    side_effect=AramRequiredUpstreamError(
                        "read_timeout",
                        "timeout",
                    ),
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value=optional,
                ),
            ):
                restored = asyncio.run(
                    query_aram_augments(restarted, hero="Ahri")
                )
            self.assertEqual(restored["source"], "stale")
            self.assertTrue(restored["stale"])
            self.assertEqual(
                restored["fallback_reason"],
                "opgg-aram-augments:read_timeout",
            )
            self.assertEqual(restored["rows"], [{"name": "强化一"}])

    def test_circuit_open_uses_snapshot_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(temp)
            ctx.seed_champion()
            ctx.upstream_snapshot_store.save(
                aram_payload_source_id("Ahri"),
                live_payload(),
            )
            with (
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    side_effect=AramRequiredUpstreamError(
                        "circuit_open",
                        "open",
                        status="circuit_open",
                    ),
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value={},
                ),
            ):
                result = build_aram_augment_payload(ctx, "阿狸")
            self.assertEqual(result["source"], "snapshot")
            self.assertTrue(result["stale"])

    def test_missing_or_expired_snapshot_returns_503(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(temp)
            ctx.seed_champion()
            old = datetime.now(timezone.utc) - timedelta(hours=2)
            ctx.upstream_snapshot_store.save(
                aram_payload_source_id("Ahri"),
                live_payload(),
                captured_at=old,
            )
            with (
                patch.dict(
                    os.environ,
                    {"ARAM_SNAPSHOT_MAX_AGE_SECONDS": "60"},
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    side_effect=AramRequiredUpstreamError(
                        "read_timeout",
                        "timeout",
                    ),
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value={},
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    build_aram_augment_payload(ctx, "阿狸")
            self.assertEqual(caught.exception.status_code, 503)
            self.assertIn("expired", str(caught.exception.detail))
            self.assertNotIn("https://", str(caught.exception.detail))

    def test_optional_build_failure_reuses_previous_optional_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(temp)
            ctx.seed_champion()
            ctx.upstream_snapshot_store.save(
                aram_payload_source_id("Ahri"),
                live_payload(),
            )
            augment = {
                "rows": [{"name": "新强化"}],
                "source_url": "https://op.gg/ahri/augments",
                "duration_ms": 8.0,
                "attempts": 1,
                "http_status": 200,
            }
            unavailable = {
                "item_builds": [],
                "starter_items": [],
                "boots": [],
                "summoner_spells": [],
                "skill_order": [],
                "status": "unavailable",
                "error_class": "read_timeout",
                "duration_ms": 4.0,
                "attempts": 1,
                "http_status": 0,
            }
            with (
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    return_value=augment,
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value=unavailable,
                ),
            ):
                result = build_aram_augment_payload(ctx, "阿狸")
            self.assertEqual(result["source"], "opgg")
            self.assertFalse(result["stale"])
            self.assertEqual(result["rows"], [{"name": "新强化"}])
            self.assertEqual(result["item_builds"], live_payload()["item_builds"])
            self.assertEqual(result["timing"]["build_status"], "snapshot")

    def test_snapshot_write_failure_does_not_hide_live_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FailingSaveStore(Path(temp))
            ctx = Context(temp, store=store)
            ctx.seed_champion()
            augment = {
                "rows": [{"name": "强化一"}],
                "source_url": "https://op.gg/ahri/augments",
                "duration_ms": 8.0,
                "attempts": 1,
                "http_status": 200,
            }
            optional = {
                "item_builds": [],
                "starter_items": [],
                "boots": [],
                "summoner_spells": [],
                "skill_order": [],
                "status": "ok",
                "error_class": "",
                "duration_ms": 4.0,
                "attempts": 1,
                "http_status": 200,
            }
            with (
                patch.object(
                    aram_augments_service,
                    "_fetch_augment_rows",
                    return_value=augment,
                ),
                patch.object(
                    aram_augments_service,
                    "_fetch_optional_build",
                    return_value=optional,
                ),
            ):
                result = build_aram_augment_payload(ctx, "阿狸")
            self.assertEqual(result["source"], "opgg")
            self.assertEqual(
                result["timing"]["snapshot_write_error"],
                "OSError",
            )


if __name__ == "__main__":
    unittest.main()
