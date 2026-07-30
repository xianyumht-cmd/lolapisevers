import json
import threading
import time
import unittest

import requests

from services.upstream_http_client import UpstreamHttpClient, classify_request_exception


class FakeResponse:
    def __init__(self, status=200, text="{}", headers=None):
        self.status_code = status
        self.text = text
        self.headers = dict(headers or {})
        self.ok = 200 <= status < 400
        self.closed = False

    def close(self):
        self.closed = True


class SequenceSession:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, url, **kwargs):
        with self.lock:
            self.calls.append((method, url, kwargs))
            item = self.sequence.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        return item


class UpstreamHttpClientTests(unittest.TestCase):
    def make_client(self, session, **kwargs):
        return UpstreamHttpClient(
            session=session,
            sleep_fn=kwargs.pop("sleep_fn", lambda _seconds: None),
            random_fn=kwargs.pop("random_fn", lambda: 0.0),
            **kwargs,
        )

    def test_get_json_uses_split_timeout_and_parses_payload(self):
        session = SequenceSession([FakeResponse(200, '{"hero": []}')])
        client = self.make_client(session, connect_timeout=1.25, read_timeout=4.5)
        result = client.get_json("hero-list", "https://example.invalid/heroes")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"hero": []})
        self.assertEqual(session.calls[0][2]["timeout"], (1.25, 4.5))

    def test_retryable_http_status_retries_with_backoff(self):
        sleeps = []
        first = FakeResponse(503, "busy")
        session = SequenceSession([first, FakeResponse(200, '{"ok": true}')])
        client = self.make_client(session, attempts=2, base_backoff_seconds=0.5, sleep_fn=sleeps.append)
        result = client.get_json("shards", "https://example.invalid/shards")
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [0.5])
        self.assertTrue(first.closed)

    def test_retry_after_header_is_bounded(self):
        sleeps = []
        session = SequenceSession([
            FakeResponse(429, "slow", {"Retry-After": "9"}),
            FakeResponse(200, "{}"),
        ])
        client = self.make_client(session, attempts=2, max_backoff_seconds=1.5, sleep_fn=sleeps.append)
        result = client.get_json("rate-limited", "https://example.invalid/data")
        self.assertTrue(result.ok)
        self.assertEqual(sleeps, [1.5])

    def test_conditional_headers_and_not_modified(self):
        session = SequenceSession([FakeResponse(304, "", {"ETag": "new-tag"})])
        client = self.make_client(session)
        result = client.get_json(
            "conditional",
            "https://example.invalid/data",
            etag="old-tag",
            last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        )
        headers = session.calls[0][2]["headers"]
        self.assertEqual(headers["If-None-Match"], "old-tag")
        self.assertIn("If-Modified-Since", headers)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "not_modified")
        self.assertEqual(result.etag, "new-tag")

    def test_json_and_validation_errors_are_structured_and_not_retried(self):
        bad_json_session = SequenceSession([FakeResponse(200, "{bad")])
        result = self.make_client(bad_json_session, attempts=3).get_json(
            "bad-json", "https://example.invalid/data"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.error_class, "json_error")
        self.assertEqual(len(bad_json_session.calls), 1)

        validation_session = SequenceSession([FakeResponse(200, '{"value": 1}')])
        result = self.make_client(validation_session).get_json(
            "bad-shape",
            "https://example.invalid/data",
            validate=lambda _value: (_ for _ in ()).throw(ValueError("missing hero list")),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.error_class, "validation_error")

    def test_connection_exceptions_are_classified(self):
        cases = [
            (requests.exceptions.ConnectTimeout("connect"), "connect_timeout"),
            (requests.exceptions.ReadTimeout("read"), "read_timeout"),
            (requests.exceptions.SSLError("certificate verify failed"), "tls_error"),
            (requests.exceptions.ConnectionError("getaddrinfo failed"), "dns_error"),
            (requests.exceptions.ConnectionError("Connection refused"), "connection_refused"),
            (requests.exceptions.ConnectionError("No route to host"), "network_unreachable"),
        ]
        for exc, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_request_exception(exc).error_class, expected)

    def test_connect_timeout_retries_then_returns_structured_error(self):
        session = SequenceSession([
            requests.exceptions.ConnectTimeout("first"),
            requests.exceptions.ConnectTimeout("second"),
        ])
        client = self.make_client(session, attempts=2)
        result = client.get_json("timeout-source", "https://example.invalid/data")
        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.error.error_class, "connect_timeout")
        state = client.state("timeout-source")["timeout-source"]
        self.assertEqual(state["consecutive_failures"], 1)

    def test_circuit_opens_and_blocks_next_request(self):
        session = SequenceSession([
            requests.exceptions.ReadTimeout("one"),
            requests.exceptions.ReadTimeout("two"),
        ])
        client = self.make_client(
            session,
            attempts=1,
            circuit_failure_threshold=2,
            circuit_open_seconds=60,
        )
        self.assertFalse(client.get_json("circuit", "https://example.invalid/data").ok)
        second = client.get_json("circuit", "https://example.invalid/data")
        self.assertEqual(second.circuit_state, "open")
        blocked = client.get_json("circuit", "https://example.invalid/data")
        self.assertEqual(blocked.status, "circuit_open")
        self.assertEqual(len(session.calls), 2)

    def test_half_open_success_closes_circuit(self):
        clock = [10.0]
        session = SequenceSession([
            requests.exceptions.ReadTimeout("one"),
            FakeResponse(200, "{}"),
        ])
        client = self.make_client(
            session,
            attempts=1,
            circuit_failure_threshold=1,
            circuit_open_seconds=5,
            monotonic_fn=lambda: clock[0],
        )
        first = client.get_json("recover", "https://example.invalid/data")
        self.assertEqual(first.circuit_state, "open")
        clock[0] = 16.0
        recovered = client.get_json("recover", "https://example.invalid/data")
        self.assertTrue(recovered.ok)
        state = client.state("recover")["recover"]
        self.assertEqual(state["circuit_state"], "closed")
        self.assertEqual(state["consecutive_failures"], 0)

    def test_singleflight_shares_one_request(self):
        entered = threading.Event()
        release = threading.Event()

        def delayed_response():
            entered.set()
            release.wait(2)
            return FakeResponse(200, '{"value": 1}')

        session = SequenceSession([delayed_response])
        client = self.make_client(session)
        results = []

        def worker():
            results.append(client.get_json("shared-source", "https://example.invalid/data"))

        first = threading.Thread(target=worker)
        second = threading.Thread(target=worker)
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        time.sleep(0.05)
        release.set()
        first.join(2)
        second.join(2)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item.ok for item in results))
        self.assertEqual(sum(1 for item in results if item.shared), 1)

    def test_source_id_and_url_validation(self):
        client = self.make_client(SequenceSession([]))
        with self.assertRaises(ValueError):
            client.get_json("../secret", "https://example.invalid/data")
        invalid = client.get_json("safe-source", "file:///etc/passwd")
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.error.error_class, "invalid_url")

    def test_error_payload_does_not_expose_url(self):
        secret_url = "https://user:password@example.invalid/private?token=secret"
        session = SequenceSession([requests.exceptions.ReadTimeout("read timed out")])
        client = self.make_client(session, attempts=1)
        result = client.get_json("redacted-source", secret_url)
        rendered = json.dumps(result.__dict__, default=lambda value: value.__dict__)
        self.assertNotIn("password", rendered)
        self.assertNotIn("token=secret", rendered)
        self.assertIn("redacted-source", rendered)


if __name__ == "__main__":
    unittest.main()
