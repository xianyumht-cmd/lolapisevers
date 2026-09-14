from __future__ import annotations

import threading
import time
import unittest

from services.upstream_http_client import UpstreamHttpClient


class BlockingControlSession:
    def __init__(self, exc_type: type[BaseException]) -> None:
        self.exc_type = exc_type
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.lock = threading.Lock()

    def request(self, _method: str, _url: str, **_kwargs: object) -> object:
        with self.lock:
            self.calls += 1
        self.entered.set()
        self.release.wait(2)
        raise self.exc_type("control signal")


class UpstreamSingleflightControlExceptionTests(unittest.TestCase):
    def test_owner_control_exception_wakes_joined_follower(self) -> None:
        for exc_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exc_type=exc_type.__name__):
                session = BlockingControlSession(exc_type)
                client = UpstreamHttpClient(
                    session=session,
                    attempts=1,
                    sleep_fn=lambda _seconds: None,
                    random_fn=lambda: 0.0,
                )
                errors: list[type[BaseException]] = []
                follower_started = threading.Event()

                def owner() -> None:
                    try:
                        client.get_json("shared-control", "https://example.invalid/data")
                    except BaseException as exc:
                        errors.append(type(exc))

                def follower() -> None:
                    follower_started.set()
                    try:
                        client.get_json("shared-control", "https://example.invalid/data")
                    except BaseException as exc:
                        errors.append(type(exc))

                first = threading.Thread(target=owner)
                second = threading.Thread(target=follower)
                first.start()
                self.assertTrue(session.entered.wait(1))
                second.start()
                self.assertTrue(follower_started.wait(1))
                time.sleep(0.05)
                session.release.set()
                first.join(2)
                second.join(2)

                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(session.calls, 1)
                self.assertEqual(errors.count(exc_type), 2)
                self.assertFalse(client.state("shared-control")["shared-control"]["in_flight"])


if __name__ == "__main__":
    unittest.main()
