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


class FakeDatabase:
    def __init__(self, *, ping_ok: bool = True, error: Exception | None = None):
        self.ping_ok = ping_ok
        self.error = error
        self.ping_calls = 0

    def ping(self) -> bool:
        self.ping_calls += 1
        if self.error is not None:
            raise self.error
        return self.ping_ok


class FakeContext:
    def __init__(
        self,
        mysql_up: bool,
        browser_up: bool,
        *,
        db_error: Exception | None = None,
    ):
        self._db = (
            FakeDatabase(error=db_error)
            if mysql_up
            else None
        )
        self.db_error_message = (
            "mysql://root:do-not-expose@database"
            if not mysql_up or db_error is not None
            else ""
        )
        async def check_readiness():
            return {
                "browser_up": browser_up,
                "session_authenticated": browser_up,
                "reason": "authenticated" if browser_up else "browser_down",
            }

        self.so1_client = SimpleNamespace(
            _browser=FakeBrowser(browser_up),
            _max_concurrent_pages=2,
            check_readiness=check_readiness,
        )

    def ensure_db(self):
        return self._db


def make_request(
    mysql_up: bool,
    browser_up: bool,
    *,
    db_error: Exception | None = None,
):
    ctx = FakeContext(
        mysql_up=mysql_up,
        browser_up=browser_up,
        db_error=db_error,
    )
    state = SimpleNamespace(
        ctx=ctx,
        so1_client=ctx.so1_client,
        build_info={
            "service": "lolapisevers",
            "commit_sha": "a" * 40,
            "commit_complete": True,
        },
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_when_mysql_ping_and_browser_are_up(self):
        request = make_request(mysql_up=True, browser_up=True)
        payload = await health(request)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["liveness"], "up")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["mysql"], "up")
        self.assertEqual(payload["so1_browser"], "up")
        self.assertEqual(
            payload["dependencies"]["mysql"]["check"],
            "select_1",
        )
        self.assertEqual(request.app.state.ctx._db.ping_calls, 1)

    async def test_live_but_not_ready_when_mysql_is_missing(self):
        payload = await health(make_request(mysql_up=False, browser_up=True))

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["liveness"], "up")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["mysql"], "down")
        self.assertEqual(payload["mysql_error"], "database_unavailable")

    async def test_real_ping_failure_is_down_and_does_not_leak_message(self):
        payload = await health(
            make_request(
                mysql_up=True,
                browser_up=True,
                db_error=RuntimeError("mysql://root:secret@10.0.0.2"),
            )
        )

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["mysql"], "down")
        self.assertEqual(payload["mysql_error"], "RuntimeError")
        serialized = str(payload)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("10.0.0.2", serialized)

    async def test_live_but_not_ready_when_browser_is_down(self):
        payload = await health(make_request(mysql_up=True, browser_up=False))

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["liveness"], "up")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["so1_browser"], "down")

    async def test_browser_connected_but_session_missing_is_not_ready(self):
        request = make_request(mysql_up=True, browser_up=True)

        async def unauthenticated():
            return {"browser_up": True, "session_authenticated": False, "reason": "session_missing"}

        request.app.state.so1_client.check_readiness = unauthenticated
        request.app.state.ctx.so1_client.check_readiness = unauthenticated
        payload = await health(request)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["so1_browser"], "up")
        self.assertEqual(payload["so1_session"], "down")

    async def test_lolban_is_optional(self):
        payload = await health(make_request(mysql_up=True, browser_up=True))

        self.assertTrue(payload["ready"])
        self.assertFalse(payload["dependencies"]["lolban"]["required"])


class HealthRouteTests(unittest.TestCase):
    def make_app(self, *, mysql_up: bool, browser_up: bool) -> FastAPI:
        app = FastAPI()
        ctx = FakeContext(mysql_up=mysql_up, browser_up=browser_up)
        app.state.ctx = ctx
        app.state.so1_client = ctx.so1_client
        app.state.build_info = {
            "schema_version": "1",
            "service": "lolapisevers",
            "commit_sha": "b" * 40,
            "commit_complete": True,
        }
        app.include_router(router)
        return app

    def test_health_remains_http_200_when_degraded(self):
        with TestClient(
            self.make_app(mysql_up=False, browser_up=False)
        ) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["liveness"], "up")
        self.assertFalse(response.json()["ready"])

    def test_readyz_returns_503_when_required_dependency_fails(self):
        with TestClient(
            self.make_app(mysql_up=True, browser_up=False)
        ) as client:
            response = client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])
        self.assertEqual(response.json()["dependencies"]["so1_browser"]["status"], "down")

    def test_readyz_returns_200_when_required_dependencies_are_up(self):
        with TestClient(
            self.make_app(mysql_up=True, browser_up=True)
        ) as client:
            response = client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])

    def test_livez_is_200_even_when_dependencies_fail(self):
        with TestClient(
            self.make_app(mysql_up=False, browser_up=False)
        ) as client:
            response = client.get("/livez")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["liveness"], "up")
        self.assertNotIn("dependencies", response.json())

    def test_build_info_endpoint_returns_loaded_metadata(self):
        with TestClient(
            self.make_app(mysql_up=False, browser_up=False)
        ) as client:
            response = client.get("/build-info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commit_sha"], "b" * 40)
        self.assertTrue(response.json()["commit_complete"])


if __name__ == "__main__":
    unittest.main()
