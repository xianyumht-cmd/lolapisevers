import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.query_observability import (
    OBSERVABILITY_SCHEMA_VERSION,
    build_query_observability,
)


class FakeCache:
    def __init__(self, keys=None, size=0):
        self.keys = set(keys or [])
        self.size = int(size)

    def contains(self, key):
        return key in self.keys

    def get(self, key):
        return object() if key in self.keys else None

    def __len__(self):
        return self.size


class FakeClient:
    def __init__(self, states=None, now=1000.0):
        self._states = dict(states or {})
        self._now = float(now)

    def state(self):
        return self._states

    def monotonic_fn(self):
        return self._now


class FakeStore:
    def __init__(self, root, statuses=None):
        self.root = Path(root)
        self.statuses = dict(statuses or {})

    def status(self, source_id, max_age_seconds=None):
        value = dict(
            self.statuses.get(
                source_id,
                {
                    "snapshot_status": "missing",
                    "snapshot_ok": False,
                },
            )
        )
        value.setdefault("source_id", source_id)
        value.setdefault("path", str(self.root / f"{source_id}.json"))
        value.setdefault("last_refresh_error_message", "")
        return value


def hit(age=30, *, captured_at="2026-07-29T05:00:00+00:00", error_class=""):
    return {
        "snapshot_status": "hit",
        "snapshot_ok": True,
        "captured_at": captured_at,
        "age_seconds": age,
        "last_success_at": captured_at,
        "last_refresh_error_at": "2026-07-29T05:01:00+00:00" if error_class else "",
        "last_refresh_error_class": error_class,
        "path": "D:/private/upstream_snapshots/secret.json",
        "last_refresh_error_message": "https://secret.invalid/?token=DO_NOT_LEAK",
    }


def context(root, *, states=None, statuses=None, shard_keys=None, aram_keys=None, aram_size=0):
    return SimpleNamespace(
        upstream_http_client=FakeClient(states),
        upstream_snapshot_store=FakeStore(root, statuses),
        shard_cache=FakeCache(shard_keys, len(shard_keys or [])),
        aram_augment_cache=FakeCache(aram_keys, aram_size),
        aram_image_cache=FakeCache(size=2),
    )


class QueryObservabilityTests(unittest.TestCase):
    def test_cache_and_live_states_are_summarized(self):
        with tempfile.TemporaryDirectory() as temp:
            states = {
                "lol-shard-data": {
                    "circuit_state": "closed",
                    "consecutive_failures": 0,
                    "last_success_at_monotonic": 900.0,
                    "last_error_at_monotonic": 0.0,
                    "last_error_class": "",
                    "open_remaining_seconds": 0,
                    "in_flight": False,
                },
                "lol-hero-list": {
                    "circuit_state": "closed",
                    "consecutive_failures": 0,
                    "last_success_at_monotonic": 920.0,
                    "last_error_at_monotonic": 0.0,
                    "last_error_class": "",
                    "open_remaining_seconds": 0,
                    "in_flight": False,
                },
            }
            statuses = {
                "lol-shard-data": hit(10),
                "lol-hero-list": hit(20),
            }
            payload = build_query_observability(
                context(
                    temp,
                    states=states,
                    statuses=statuses,
                    shard_keys={"sources"},
                    aram_keys={"champion_catalog", "aram_augments:ahri"},
                    aram_size=2,
                ),
                lolban_health_loader=lambda: {
                    "configured": True,
                    "provider_count": 2,
                    "fresh_cache_entries": 1,
                    "stale_cache_entries": 1,
                    "persistent_snapshot_enabled": True,
                    "persistent_snapshot_status": "saved",
                },
            )

            self.assertEqual(payload["schema_version"], OBSERVABILITY_SCHEMA_VERSION)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["sources"]["shard_data"]["mode"], "cache")
            self.assertEqual(payload["sources"]["hero_catalog"]["mode"], "cache")
            self.assertEqual(payload["sources"]["aram"]["mode"], "cache")
            self.assertEqual(payload["sources"]["lolban"]["mode"], "cache")
            self.assertEqual(payload["summary"]["cache"], 4)

    def test_open_circuit_and_error_use_snapshot_or_stale_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            states = {
                "lol-shard-data": {
                    "circuit_state": "open",
                    "consecutive_failures": 3,
                    "last_error_at_monotonic": 990.0,
                    "last_error_class": "read_timeout",
                    "open_remaining_seconds": 20,
                    "in_flight": False,
                },
                "lol-hero-list": {
                    "circuit_state": "closed",
                    "consecutive_failures": 1,
                    "last_error_at_monotonic": 995.0,
                    "last_error_class": "dns_error",
                    "open_remaining_seconds": 0,
                    "in_flight": False,
                },
            }
            payload = build_query_observability(
                context(
                    temp,
                    states=states,
                    statuses={
                        "lol-shard-data": hit(120),
                        "lol-hero-list": hit(60, error_class="dns_error"),
                    },
                ),
                lolban_health_loader=lambda: {"configured": False},
            )

            self.assertEqual(payload["sources"]["shard_data"]["mode"], "snapshot")
            self.assertEqual(payload["sources"]["hero_catalog"]["mode"], "stale")
            self.assertEqual(payload["sources"]["lolban"]["mode"], "unavailable")
            self.assertEqual(payload["status"], "degraded")
            self.assertEqual(
                payload["sources"]["shard_data"]["circuit"]["last_error_class"],
                "read_timeout",
            )
            self.assertNotIn(
                "last_error_at_monotonic",
                payload["sources"]["shard_data"]["circuit"],
            )

    def test_dynamic_aram_states_are_aggregated_without_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "aram-mayhem-secretHero.json").write_text("{}", encoding="utf-8")
            (root / "aram-mayhem-secretHero.status.json").write_text("{}", encoding="utf-8")
            (root / "aram-mayhem-other.bad.20260729.json").write_text("{}", encoding="utf-8")
            states = {
                "opgg-aram-augments-secretHero": {
                    "circuit_state": "open",
                    "consecutive_failures": 4,
                    "last_error_at_monotonic": 998.0,
                    "last_error_class": "https://private.invalid/?token=abc",
                    "open_remaining_seconds": 12,
                    "in_flight": True,
                },
                "opgg-aram-build-secretHero": {
                    "circuit_state": "closed",
                    "consecutive_failures": 0,
                    "last_success_at_monotonic": 996.0,
                    "last_error_class": "",
                    "open_remaining_seconds": 0,
                    "in_flight": False,
                },
            }
            payload = build_query_observability(
                context(
                    temp,
                    states=states,
                    statuses={
                        "aram-mayhem-secretHero": hit(300),
                    },
                ),
                lolban_health_loader=lambda: {"configured": False},
            )

            aram = payload["sources"]["aram"]
            self.assertEqual(aram["mode"], "snapshot")
            self.assertEqual(aram["snapshots"]["observed_count"], 1)
            self.assertEqual(aram["snapshots"]["available_count"], 1)
            self.assertEqual(aram["upstreams"]["augment_page"]["circuit_open_count"], 1)
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("secretHero", serialized)
            self.assertNotIn("private.invalid", serialized)
            self.assertNotIn("token=abc", serialized)
            self.assertNotIn(str(root), serialized)

    def test_response_has_no_sensitive_keys_or_raw_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = build_query_observability(
                context(
                    temp,
                    statuses={
                        "lol-shard-data": hit(error_class="read_timeout"),
                        "lol-hero-list": hit(error_class="dns_error"),
                    },
                ),
                lolban_health_loader=lambda: {
                    "configured": True,
                    "provider_count": 1,
                    "providers": ["provider-with-secret"],
                    "last_error_class": "ReadTimeout",
                    "last_error_at": "2026-07-29T05:00:00+00:00",
                    "persistent_snapshot_enabled": True,
                    "persistent_snapshot_status": "restored",
                    "persistent_snapshot_restored_entries": 2,
                },
            )
            serialized = json.dumps(payload, ensure_ascii=False).lower()
            for forbidden in (
                "http://",
                "https://",
                "do_not_leak",
                "upstream_snapshots",
                "provider-with-secret",
                '"path"',
                '"url"',
                '"message"',
                '"query"',
                '"qq"',
                '"token"',
                '"cookie"',
                '"password"',
                '"headers"',
            ):
                self.assertNotIn(forbidden, serialized)

    def test_missing_context_returns_safe_down_payload(self):
        payload = build_query_observability(None)
        self.assertEqual(payload["status"], "down")
        self.assertEqual(payload["error_class"], "context_unavailable")
        self.assertEqual(payload["summary"]["unavailable"], 4)
        self.assertEqual(payload["sources"], {})


if __name__ == "__main__":
    unittest.main()
