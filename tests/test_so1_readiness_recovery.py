import asyncio
import json
import os
import tempfile
import unittest

from services.so1_readiness_service import (
    _challenge_detected,
    _classify_user_me,
    ensure_so1_readiness,
)


class FakePage:
    def __init__(self, client):
        self.client = client

    async def goto(self, *_args, **_kwargs):
        return None

    async def evaluate(self, script, *_args):
        if "document.body" in script:
            if self.client.challenge:
                return {
                    "url": "https://lolso1.com/",
                    "title": "Security verification",
                    "text": "Please verify you are human",
                }
            return {
                "url": "https://lolso1.com/",
                "title": "搜联盟",
                "text": "normal application content",
            }
        if "r1.lolso1.com/user/me" in script:
            if self.client.authenticated:
                return {
                    "status": 200,
                    "ok": True,
                    "data": {
                        "errCode": "0000",
                        "data": {"username": "tester"},
                    },
                }
            return {
                "status": 200,
                "ok": True,
                "data": {
                    "errCode": "ERR_UNAUTHORIZED",
                    "data": None,
                },
            }
        raise AssertionError(f"unexpected script: {script[:80]}")


class FakeContext:
    def __init__(self, client):
        self.client = client
        self.closed = False

    async def new_page(self):
        return FakePage(self.client)

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, client):
        self.client = client
        self.context_calls = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        self.context_calls.append(kwargs)
        return FakeContext(self.client)


class FakeClient:
    def __init__(
        self,
        state_path,
        *,
        authenticated=False,
        challenge=False,
        username="account",
        password="password",
        fail_login=False,
    ):
        self._state_path = state_path
        self.authenticated = authenticated
        self.challenge = challenge
        self.username = username
        self.password = password
        self.fail_login = fail_login
        self.timeout_ms = 5000
        self._browser = FakeBrowser(self)
        self._readiness_cache = (0.0, False, "not_checked")
        self.login_calls = 0
        self.probe_calls = 0

    async def check_readiness(self, ttl_seconds=30.0):
        self.probe_calls += 1
        if self.authenticated:
            return {
                "browser_up": True,
                "session_authenticated": True,
                "reason": "authenticated",
            }
        if not os.path.isfile(self._state_path):
            return {
                "browser_up": True,
                "session_authenticated": False,
                "reason": "session_missing",
            }
        try:
            with open(self._state_path, "r", encoding="utf-8") as handle:
                json.load(handle)
        except Exception:
            return {
                "browser_up": True,
                "session_authenticated": False,
                "reason": "session_expired_or_challenge",
            }
        return {
            "browser_up": True,
            "session_authenticated": False,
            "reason": "session_expired_or_challenge",
        }

    async def _login(self, _page):
        self.login_calls += 1
        await asyncio.sleep(0.01)
        if self.fail_login:
            raise RuntimeError("do-not-expose upstream response or password")
        self.authenticated = True
        with open(self._state_path, "w", encoding="utf-8") as handle:
            json.dump({"cookies": [{"name": "session"}]}, handle)
        self._readiness_cache = (0.0, True, "authenticated")


class So1ReadinessRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, ".so1_state.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_state(self, payload=None):
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(payload or {"cookies": [{"name": "session"}]}, handle)

    async def test_healthy_session_does_not_open_recovery_context(self):
        self.write_state()
        client = FakeClient(self.state_path, authenticated=True)

        result = await ensure_so1_readiness(client)

        self.assertTrue(result["session_authenticated"])
        self.assertEqual(result["reason"], "authenticated")
        self.assertEqual(client.login_calls, 0)
        self.assertEqual(client._browser.context_calls, [])

    async def test_expired_session_is_auto_recovered(self):
        self.write_state()
        client = FakeClient(self.state_path)

        result = await ensure_so1_readiness(client)

        self.assertTrue(result["session_authenticated"])
        self.assertEqual(result["reason"], "authenticated")
        self.assertEqual(result["recovery"], "auto_recovered")
        self.assertEqual(result["original_reason"], "session_expired")
        self.assertEqual(client.login_calls, 1)

    async def test_concurrent_checks_only_login_once(self):
        self.write_state()
        client = FakeClient(self.state_path)

        first, second = await asyncio.gather(
            ensure_so1_readiness(client),
            ensure_so1_readiness(client),
        )

        self.assertTrue(first["session_authenticated"])
        self.assertTrue(second["session_authenticated"])
        self.assertEqual(client.login_calls, 1)

    async def test_login_failure_enters_cooldown_without_leaking_error(self):
        self.write_state()
        client = FakeClient(self.state_path, fail_login=True)

        first = await ensure_so1_readiness(client)
        second = await ensure_so1_readiness(client)

        self.assertEqual(first["reason"], "login_failed")
        self.assertEqual(first["error_class"], "RuntimeError")
        self.assertNotIn("do-not-expose", str(first))
        self.assertEqual(second["reason"], "login_cooldown")
        self.assertEqual(client.login_calls, 1)

    async def test_challenge_blocks_auto_login(self):
        self.write_state()
        client = FakeClient(self.state_path, challenge=True)

        first = await ensure_so1_readiness(client)
        second = await ensure_so1_readiness(client)

        self.assertEqual(first["reason"], "challenge_detected")
        self.assertEqual(first["recovery"], "blocked")
        self.assertEqual(second["reason"], "challenge_detected")
        self.assertEqual(client.login_calls, 0)

    async def test_missing_credentials_does_not_attempt_login(self):
        self.write_state()
        client = FakeClient(self.state_path, username="", password="")

        result = await ensure_so1_readiness(client)

        self.assertEqual(result["reason"], "credentials_missing")
        self.assertEqual(result["recovery"], "not_attempted")
        self.assertEqual(client.login_calls, 0)

    async def test_invalid_state_uses_blank_context_and_recovers(self):
        with open(self.state_path, "w", encoding="utf-8") as handle:
            handle.write("{invalid")
        client = FakeClient(self.state_path)

        result = await ensure_so1_readiness(client)

        self.assertTrue(result["session_authenticated"])
        self.assertEqual(result["recovery"], "auto_recovered")
        self.assertEqual(client.login_calls, 1)
        self.assertTrue(client._browser.context_calls)
        self.assertEqual(client._browser.context_calls[0], {})

    async def test_unauthorized_user_me_is_precisely_session_expired(self):
        authenticated, reason = _classify_user_me(
            {
                "status": 200,
                "ok": True,
                "data": {"errCode": "ERR_UNAUTHORIZED", "data": None},
            }
        )

        self.assertFalse(authenticated)
        self.assertEqual(reason, "session_expired")

    async def test_generic_verified_text_is_not_a_challenge(self):
        self.assertFalse(
            _challenge_detected(
                {
                    "url": "https://lolso1.com/",
                    "title": "Profile",
                    "text": "Profile verified successfully",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
