import asyncio
import os
import threading
import time
import unittest
from unittest.mock import patch

from cache import TTLCache
from services.lolban_service import (
    LolBanService,
    _create_default_service,
    clean_payload,
)


def payload(qq: str, status: str = "正常"):
    return {
        "code": 200,
        "by": "test",
        "msg": "此账号状态正常" if status == "正常" else "此账号已被封禁",
        "data": {
            "qq": qq,
            "ban_time": "",
            "end_time": "账号状态正常" if status == "正常" else "1天",
            "status": status,
        },
    }


class FakeProvider:
    def __init__(self, name, *, result=None, error=None, delay=0):
        self.name = name
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0
        self.lock = threading.Lock()

    def query(self, qq):
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result or payload(qq)


class LolBanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_fallback_and_fresh_cache(self):
        failed = FakeProvider("primary", error=TimeoutError("secret-token-in-url"))
        success = FakeProvider("backup")
        service = LolBanService([failed, success], snapshot_store=None)

        live, source, ttl = await service.get_result("2621735529")

        self.assertEqual(source, "live")
        self.assertEqual(ttl, service.normal_cache_seconds)
        self.assertEqual(live["provider"], "backup")
        self.assertEqual(live["fallback_reason"], "provider_fallback")
        self.assertEqual(
            [item["provider"] for item in live["attempts"]],
            ["primary", "backup"],
        )
        self.assertNotIn("secret-token-in-url", str(live["attempts"]))

        cached, source, _ = await service.get_result("2621735529")
        self.assertEqual(source, "cache")
        self.assertEqual(failed.calls, 1)
        self.assertEqual(success.calls, 1)

        live["data"]["status"] = "tampered"
        self.assertEqual(cached["data"]["status"], "正常")

    async def test_banned_result_uses_longer_cache(self):
        provider = FakeProvider(
            "primary",
            result=payload("2621735529", "封禁"),
        )
        service = LolBanService(
            [provider],
            normal_cache_seconds=10,
            banned_cache_seconds=60,
            snapshot_store=None,
        )

        result, source, ttl = await service.get_result("2621735529")

        self.assertEqual(source, "live")
        self.assertEqual(result["data"]["status"], "封禁")
        self.assertEqual(ttl, 60)

    async def test_stale_result_is_used_only_after_all_providers_fail(self):
        provider = FakeProvider("primary")
        service = LolBanService(
            [provider],
            stale_cache_seconds=3600,
            snapshot_store=None,
        )
        await service.get_result("2621735529")

        service._normal_cache = TTLCache(ttl_seconds=60)
        service._banned_cache = TTLCache(ttl_seconds=60)
        provider.error = ConnectionError("provider offline")

        stale, source, ttl = await service.get_result("2621735529")

        self.assertEqual(source, "stale")
        self.assertEqual(ttl, 0)
        self.assertEqual(stale["fallback_reason"], "all_providers_failed")
        self.assertEqual(stale["stale_origin"], "memory")
        self.assertEqual(stale["data"]["status"], "正常")

    async def test_concurrent_cache_miss_is_singleflight_per_qq(self):
        provider = FakeProvider("primary", delay=0.05)
        service = LolBanService([provider], snapshot_store=None)

        results = await asyncio.gather(
            service.get_result("2621735529"),
            service.get_result("2621735529"),
            service.get_result("2621735529"),
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual({item[1] for item in results}, {"live", "cache"})

    async def test_no_provider_has_sanitized_failure(self):
        service = LolBanService([], snapshot_store=None)

        with self.assertRaisesRegex(RuntimeError, "providers_not_configured"):
            await service.get_result("2621735529")

        health = service.health()
        self.assertFalse(health["configured"])
        self.assertEqual(health["provider_count"], 0)
        self.assertEqual(
            health["last_error_class"],
            "providers_not_configured",
        )
        self.assertFalse(health["persistent_snapshot_enabled"])

    async def test_stale_store_is_bounded(self):
        provider = FakeProvider("primary")
        service = LolBanService(
            [provider],
            max_stale_entries=2,
            snapshot_store=None,
        )

        await service.get_result("10001")
        await service.get_result("10002")
        await service.get_result("10003")

        self.assertEqual(service.health()["stale_cache_entries"], 2)
        self.assertEqual(len(service._query_locks), 64)

    def test_upstream_cannot_substitute_a_different_qq(self):
        wrong_account = payload("10002")

        with self.assertRaisesRegex(RuntimeError, "qq mismatch"):
            clean_payload("10001", wrong_account)

    def test_invalid_optional_provider_config_does_not_break_service_import(self):
        with patch.dict(
            os.environ,
            {"LOL_BAN_PROVIDERS_JSON": "{"},
            clear=False,
        ):
            service = _create_default_service()

        health = service.health()
        self.assertFalse(health["configured"])
        self.assertEqual(
            health["configuration_error_code"],
            "invalid_provider_configuration",
        )
        self.assertEqual(
            health["configuration_error_class"],
            "RuntimeError",
        )


if __name__ == "__main__":
    unittest.main()
