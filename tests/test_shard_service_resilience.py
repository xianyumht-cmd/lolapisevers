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
from services.persistent_snapshot_store import PersistentSnapshotStore
from services.shard_service import (
    SHARD_DATA_SOURCE_ID,
    SHARD_HERO_SOURCE_ID,
    DEFAULT_SHARD_DATA_URL,
    SHARD_DATA_MIRRORS,
    load_shard_sources,
    query_shard,
)
from services.upstream_http_client import UpstreamError, UpstreamResponse


SHARDS = {
    "Kalista": {
        "pick_rate": 0.12,
        "win_rate": 0.51,
        "shards": [
            {
                "name": "低选率",
                "id": "2",
                "pick_rate": 0.1,
                "win_rate": 0.4,
            },
            {
                "name": "高选率",
                "id": "1",
                "pick_rate": 0.8,
                "win_rate": 0.6,
            },
        ],
    }
}
HEROES = {
    "hero": [
        {
            "alias": "Kalista",
            "name": "卡莉丝塔",
            "title": "复仇之矛",
            "keywords": "滑板鞋",
        }
    ]
}


def ok(
    source,
    data,
    *,
    status="ok",
    status_code=200,
    etag="",
    last_modified="",
):
    return UpstreamResponse(
        True,
        source,
        status,
        status_code=status_code,
        attempts=1,
        data=data,
        etag=etag,
        last_modified=last_modified,
    )


def failed(source, error_class="read_timeout", *, status="failed"):
    return UpstreamResponse(
        False,
        source,
        status,
        attempts=2,
        error=UpstreamError(error_class, error_class, True),
        circuit_state="open" if status == "circuit_open" else "closed",
    )


class FakeClient:
    def __init__(self, responses):
        self.responses = {
            key: list(value)
            for key, value in responses.items()
        }
        self.calls = []

    def get_json(self, source_id, url, **kwargs):
        self.calls.append((source_id, url, dict(kwargs)))
        queue = self.responses[source_id]
        if not queue:
            raise AssertionError(f"no response for {source_id}")
        return queue.pop(0)


class FailingSaveStore(PersistentSnapshotStore):
    def save(self, *args, **kwargs):
        raise OSError("disk full")


class Context:
    def __init__(self, root, client, *, ttl=600, store=None):
        self.config = SimpleNamespace(
            shard_data_url="https://example.invalid/shards.json",
            shard_hero_url="https://example.invalid/heroes.json",
            shard_cache_seconds=ttl,
        )
        self.shard_cache = TTLCache(ttl_seconds=ttl)
        self.upstream_http_client = client
        self.upstream_snapshot_store = (
            store or PersistentSnapshotStore(Path(root))
        )
        self.logger = SimpleNamespace(
            warning=lambda *args, **kwargs: None
        )


class ShardResilienceTests(unittest.TestCase):
    def test_live_sources_are_saved_and_endpoint_shape_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(
                            SHARD_DATA_SOURCE_ID,
                            SHARDS,
                            etag='"s1"',
                        )
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        ok(
                            SHARD_HERO_SOURCE_ID,
                            HEROES,
                            etag='"h1"',
                        )
                    ],
                }
            )
            ctx = Context(temp, client)
            result = asyncio.run(query_shard(ctx, hero="滑板鞋"))

            self.assertEqual(result["hero"]["alias"], "Kalista")
            self.assertEqual(result["rows"][0]["name"], "高选率")
            self.assertEqual(result["source"], "live")
            self.assertFalse(result["stale"])
            self.assertEqual(result["provider"], "badspacebar")
            self.assertIn("source_details", result)
            self.assertTrue(
                (Path(temp) / f"{SHARD_DATA_SOURCE_ID}.json").is_file()
            )
            self.assertTrue(
                (Path(temp) / f"{SHARD_HERO_SOURCE_ID}.json").is_file()
            )

    def test_restart_uses_stale_snapshots_when_network_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Context(
                temp,
                FakeClient(
                    {
                        SHARD_DATA_SOURCE_ID: [
                            ok(SHARD_DATA_SOURCE_ID, SHARDS)
                        ],
                        SHARD_HERO_SOURCE_ID: [
                            ok(SHARD_HERO_SOURCE_ID, HEROES)
                        ],
                    }
                ),
            )
            live = asyncio.run(query_shard(first, hero="Kalista"))
            self.assertEqual(live["source"], "live")

            second = Context(
                temp,
                FakeClient(
                    {
                        SHARD_DATA_SOURCE_ID: [
                            failed(SHARD_DATA_SOURCE_ID)
                        ],
                        SHARD_HERO_SOURCE_ID: [
                            failed(SHARD_HERO_SOURCE_ID, "dns_error")
                        ],
                    }
                ),
            )
            restored = asyncio.run(query_shard(second, hero="滑板鞋"))

            self.assertEqual(restored["source"], "stale")
            self.assertTrue(restored["stale"])
            self.assertIn("read_timeout", restored["fallback_reason"])
            self.assertIn("dns_error", restored["fallback_reason"])
            self.assertEqual(restored["hero"]["alias"], "Kalista")

    def test_conditional_304_refreshes_snapshot_and_counts_as_live(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save(
                SHARD_DATA_SOURCE_ID,
                SHARDS,
                {"etag": '"s1"', "last_modified": "Mon"},
            )
            store.save(
                SHARD_HERO_SOURCE_ID,
                HEROES,
                {"etag": '"h1"', "last_modified": "Tue"},
            )
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(
                            SHARD_DATA_SOURCE_ID,
                            None,
                            status="not_modified",
                            status_code=304,
                            etag='"s1"',
                        )
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        ok(
                            SHARD_HERO_SOURCE_ID,
                            None,
                            status="not_modified",
                            status_code=304,
                            etag='"h1"',
                        )
                    ],
                }
            )
            ctx = Context(temp, client, store=store)
            sources = load_shard_sources(ctx)

            self.assertEqual(sources["source"], "live")
            self.assertFalse(sources["stale"])
            self.assertTrue(
                sources["source_details"][SHARD_DATA_SOURCE_ID][
                    "conditional_not_modified"
                ]
            )
            self.assertEqual(client.calls[0][2]["etag"], '"s1"')
            self.assertEqual(client.calls[1][2]["etag"], '"h1"')
            self.assertEqual(
                store.load(SHARD_DATA_SOURCE_ID).metadata["etag"],
                '"s1"',
            )
            self.assertEqual(
                store.load(SHARD_HERO_SOURCE_ID).metadata["etag"],
                '"h1"',
            )

    def test_circuit_open_uses_snapshot_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save(SHARD_DATA_SOURCE_ID, SHARDS)
            store.save(SHARD_HERO_SOURCE_ID, HEROES)
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        failed(
                            SHARD_DATA_SOURCE_ID,
                            "circuit_open",
                            status="circuit_open",
                        )
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        failed(
                            SHARD_HERO_SOURCE_ID,
                            "circuit_open",
                            status="circuit_open",
                        )
                    ],
                }
            )
            result = asyncio.run(
                query_shard(
                    Context(temp, client, store=store),
                    hero="Kalista",
                )
            )
            self.assertEqual(result["source"], "snapshot")
            self.assertTrue(result["stale"])

    def test_missing_snapshot_and_failed_upstream_returns_503(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        failed(SHARD_DATA_SOURCE_ID)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        failed(SHARD_HERO_SOURCE_ID)
                    ],
                }
            )
            with self.assertRaises(HTTPException) as caught:
                load_shard_sources(Context(temp, client))
            self.assertEqual(caught.exception.status_code, 503)
            self.assertIn(
                SHARD_DATA_SOURCE_ID,
                str(caught.exception.detail),
            )
            self.assertNotIn("https://", str(caught.exception.detail))

    def test_expired_snapshot_is_not_used(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            old = datetime.now(timezone.utc) - timedelta(days=2)
            store.save(
                SHARD_DATA_SOURCE_ID,
                SHARDS,
                captured_at=old,
            )
            store.save(
                SHARD_HERO_SOURCE_ID,
                HEROES,
                captured_at=old,
            )
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        failed(SHARD_DATA_SOURCE_ID)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        failed(SHARD_HERO_SOURCE_ID)
                    ],
                }
            )
            with patch.dict(
                os.environ,
                {"SHARD_SNAPSHOT_MAX_AGE_SECONDS": "60"},
            ):
                with self.assertRaises(HTTPException) as caught:
                    load_shard_sources(
                        Context(temp, client, store=store)
                    )
            self.assertIn("expired", str(caught.exception.detail))

    def test_corrupt_snapshot_is_quarantined_and_live_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            path = store.path_for(SHARD_DATA_SOURCE_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(SHARD_DATA_SOURCE_ID, SHARDS)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        ok(SHARD_HERO_SOURCE_ID, HEROES)
                    ],
                }
            )
            result = asyncio.run(
                query_shard(
                    Context(temp, client, store=store),
                    hero="Kalista",
                )
            )
            self.assertEqual(result["source"], "live")
            self.assertTrue(path.is_file())
            self.assertTrue(
                list(
                    Path(temp).glob(
                        f"{SHARD_DATA_SOURCE_ID}.bad.*.json"
                    )
                )
            )

    def test_memory_cache_returns_cache_without_more_upstream_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(SHARD_DATA_SOURCE_ID, SHARDS)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        ok(SHARD_HERO_SOURCE_ID, HEROES)
                    ],
                }
            )
            ctx = Context(temp, client)
            first = asyncio.run(query_shard(ctx, hero="Kalista"))
            second = asyncio.run(query_shard(ctx, hero="Kalista"))
            self.assertEqual(first["source"], "live")
            self.assertEqual(second["source"], "cache")
            self.assertEqual(second["cache_origin"], "live")
            self.assertEqual(len(client.calls), 2)

    def test_one_failed_source_marks_overall_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            store.save(SHARD_HERO_SOURCE_ID, HEROES)
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(SHARD_DATA_SOURCE_ID, SHARDS)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        failed(SHARD_HERO_SOURCE_ID, "dns_error")
                    ],
                }
            )
            result = asyncio.run(
                query_shard(
                    Context(temp, client, store=store),
                    hero="Kalista",
                )
            )
            self.assertEqual(result["source"], "stale")
            self.assertEqual(
                result["source_details"][SHARD_DATA_SOURCE_ID]["mode"],
                "live",
            )
            self.assertEqual(
                result["source_details"][SHARD_HERO_SOURCE_ID]["mode"],
                "stale",
            )

    def test_snapshot_write_failure_does_not_break_live_result(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FailingSaveStore(Path(temp))
            client = FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [
                        ok(SHARD_DATA_SOURCE_ID, SHARDS)
                    ],
                    SHARD_HERO_SOURCE_ID: [
                        ok(SHARD_HERO_SOURCE_ID, HEROES)
                    ],
                }
            )
            result = asyncio.run(
                query_shard(
                    Context(temp, client, store=store),
                    hero="Kalista",
                )
            )
            self.assertEqual(result["source"], "live")
            self.assertEqual(
                result["source_details"][SHARD_DATA_SOURCE_ID][
                    "snapshot_write_error"
                ],
                "OSError",
            )


    def test_public_shard_source_recovers_through_mirror_after_connection_error(self):
        with tempfile.TemporaryDirectory() as temp:
            mirror_id = f"{SHARD_DATA_SOURCE_ID}-mirror-1"
            client = FakeClient({
                SHARD_DATA_SOURCE_ID: [failed(SHARD_DATA_SOURCE_ID, "connection_error")],
                mirror_id: [ok(mirror_id, SHARDS, etag='"foreign-etag"')],
                SHARD_HERO_SOURCE_ID: [ok(SHARD_HERO_SOURCE_ID, HEROES)],
            })
            ctx = Context(temp, client)
            ctx.config.shard_data_url = DEFAULT_SHARD_DATA_URL
            result = asyncio.run(query_shard(ctx, hero="Kalista"))
            self.assertEqual("live", result["source"])
            detail = result["source_details"][SHARD_DATA_SOURCE_ID]
            self.assertEqual("mirror-1", detail["mirror_used"])
            self.assertFalse(detail["etag_present"])
            self.assertEqual([SHARD_DATA_SOURCE_ID, mirror_id, SHARD_HERO_SOURCE_ID],
                             [call[0] for call in client.calls])
            self.assertEqual(SHARD_DATA_MIRRORS[0], client.calls[1][1])
            self.assertEqual(1, client.calls[1][2]["attempts"])
            self.assertEqual(4, client.calls[1][2]["connect_timeout"])
            self.assertEqual(10, client.calls[1][2]["read_timeout"])
            snapshot = ctx.upstream_snapshot_store.load(SHARD_DATA_SOURCE_ID)
            self.assertTrue(snapshot.ok)
            self.assertEqual("", snapshot.metadata["etag"])

    def test_mirror_failure_falls_through_to_second_mirror(self):
        with tempfile.TemporaryDirectory() as temp:
            first = f"{SHARD_DATA_SOURCE_ID}-mirror-1"
            second = f"{SHARD_DATA_SOURCE_ID}-mirror-2"
            client = FakeClient({
                SHARD_DATA_SOURCE_ID: [failed(SHARD_DATA_SOURCE_ID, "connection_error")],
                first: [failed(first, "dns_error")],
                second: [ok(second, SHARDS)],
                SHARD_HERO_SOURCE_ID: [ok(SHARD_HERO_SOURCE_ID, HEROES)],
            })
            ctx = Context(temp, client)
            ctx.config.shard_data_url = DEFAULT_SHARD_DATA_URL
            result = asyncio.run(query_shard(ctx, hero="Kalista"))
            self.assertEqual("mirror-2", result["source_details"][SHARD_DATA_SOURCE_ID]["mirror_used"])
            self.assertEqual("live", result["source"])

    def test_all_public_shard_mirrors_fail_closed_when_snapshot_expired(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            old = datetime.now(timezone.utc) - timedelta(days=8)
            store.save(SHARD_DATA_SOURCE_ID, SHARDS, captured_at=old)
            ids = [f"{SHARD_DATA_SOURCE_ID}-mirror-{i+1}" for i in range(len(SHARD_DATA_MIRRORS))]
            client = FakeClient({
                SHARD_DATA_SOURCE_ID: [failed(SHARD_DATA_SOURCE_ID, "connection_error")],
                **{i: [failed(i, "read_timeout")] for i in ids},
            })
            ctx = Context(temp, client, store=store)
            ctx.config.shard_data_url = DEFAULT_SHARD_DATA_URL
            with self.assertRaises(HTTPException) as caught:
                load_shard_sources(ctx)
            self.assertEqual(503, caught.exception.status_code)
            self.assertIn("expired", str(caught.exception.detail))
            self.assertEqual(1 + len(SHARD_DATA_MIRRORS), len(client.calls))

    def test_custom_shard_data_url_is_never_forwarded_to_public_mirrors(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient({SHARD_DATA_SOURCE_ID: [failed(SHARD_DATA_SOURCE_ID)]})
            ctx = Context(temp, client)
            with self.assertRaises(HTTPException):
                load_shard_sources(ctx)
            self.assertEqual([SHARD_DATA_SOURCE_ID], [call[0] for call in client.calls])


if __name__ == "__main__":
    unittest.main()
