import asyncio
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.cross_session import router
from so1_client import So1Client, So1ClientError


class CrossSessionTests(unittest.TestCase):
    def test_wait_seconds_is_bounded_before_browser_launch(self):
        app = FastAPI()
        app.include_router(router)

        with TestClient(app) as client:
            self.assertEqual(client.post("/cross_session_init?wait_seconds=9").status_code, 422)
            self.assertEqual(client.post("/cross_session_init?wait_seconds=601").status_code, 422)

    def test_second_manual_login_is_rejected_while_one_is_active(self):
        async def exercise_lock():
            client = So1Client(username="", password="")
            client._manual_login_lock = asyncio.Lock()
            await client._manual_login_lock.acquire()
            try:
                with self.assertRaisesRegex(So1ClientError, "already in progress"):
                    await client.bootstrap_manual_login(wait_seconds=10)
            finally:
                client._manual_login_lock.release()

        asyncio.run(exercise_lock())


if __name__ == "__main__":
    unittest.main()
