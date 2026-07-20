import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import health, router


class FakeBrowser:
    def __init__(self, connected: bool):
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class FakeContext:
    def __init__(self, mysql_up: bool, browser_up: bool):
        self._db = object() if mysql_up else None
        self.db_error_message = "database unavailable" if not mysql_up else ""
        self.so1_client = SimpleNamespace(
            _browser=FakeBrowser(browser_up),
            _max_concurrent_pages=2,
        )

    def ensure_db(self):
        return self._db


def make_request(mysql_up: bool, browser_up: bool):
    ctx = FakeContext(mysql_up=mysql_up, browser_up=browser_up)
    state = SimpleNamespace(ctx=ctx, so1_client=ctx.so1_client)
    return SimpleNamespace(app=SimpleNamespace(state=state))


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_when_mysql_and_browser_are_up(self):
        payload = await health(make_request(mysql_up=True, browser_up=True))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["liveness"], "up")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["mysql"], "up")
        self.assertEqual(payload["so1_browser"], "up")

    async def test_live_but_not_ready_when_mysql_is_down(self):
        payload = await health(make_request(mysql_up=False, browser_up=True))

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["liveness"], "up")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["mysql"], "down")
        self.assertEqual(payload["mysql_error"], "database unavailable")

    async def test_live_but_not_ready_when_browser_is_down(self):
        payload = await health(make_request(mysql_up=True, browser_up=False))

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["liveness"], "up")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["so1_browser"], "down")

    async def test_live_but_not_ready_when_all_dependencies_are_down(self):
        payload = await health(make_request(mysql_up=False, browser_up=False))

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["liveness"], "up")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["mysql"], "down")
        self.assertEqual(payload["so1_browser"], "down")


class HealthRouteTests(unittest.TestCase):
    def test_degraded_readiness_remains_observable_over_http(self):
        app = FastAPI()
        ctx = FakeContext(mysql_up=False, browser_up=False)
        app.state.ctx = ctx
        app.state.so1_client = ctx.so1_client
        app.include_router(router)

        with TestClient(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["liveness"], "up")
        self.assertFalse(response.json()["ready"])
        self.assertEqual(response.json()["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
