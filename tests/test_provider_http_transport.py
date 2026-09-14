from __future__ import annotations

import unittest

from services.provider_http_transport import ProviderHttpResponse, ProviderHttpTransport


class FakeResponse:
    def __init__(self, *, status_code: int = 200, chunks: list[bytes] | None = None, headers=None) -> None:
        self.status_code = status_code
        self._chunks = list(chunks or [b"{}"])
        self.headers = dict(headers or {})
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class ProviderHttpTransportTests(unittest.TestCase):
    def test_request_uses_split_timeout_and_preserves_payload_fields(self) -> None:
        response = FakeResponse(chunks=[b'{"ok":true}'])
        session = FakeSession(response)
        transport = ProviderHttpTransport(session=session, connect_timeout=2.5)
        files = [("evidence", (None, "text"))]

        result = transport.request(
            "post",
            "https://example.invalid/query",
            headers={"X-Test": "1"},
            params={"qq": "1"},
            data={"form": "value"},
            json_body={"json": True},
            files=files,
            timeout_seconds=8,
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body, b'{"ok":true}')
        kwargs = session.calls[0][2]
        self.assertEqual(kwargs["timeout"], (2.5, 8.0))
        self.assertEqual(kwargs["params"], {"qq": "1"})
        self.assertEqual(kwargs["data"], {"form": "value"})
        self.assertEqual(kwargs["json"], {"json": True})
        self.assertIs(kwargs["files"], files)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        self.assertTrue(response.closed)

    def test_declared_oversize_response_is_rejected_and_closed(self) -> None:
        response = FakeResponse(headers={"Content-Length": "5000"})
        transport = ProviderHttpTransport(session=FakeSession(response), max_response_bytes=1024)

        with self.assertRaisesRegex(ValueError, "provider_response_too_large"):
            transport.request("GET", "https://example.invalid/query")
        self.assertTrue(response.closed)

    def test_streamed_oversize_response_is_rejected(self) -> None:
        response = FakeResponse(chunks=[b"a" * 800, b"b" * 800])
        transport = ProviderHttpTransport(session=FakeSession(response), max_response_bytes=1024)

        with self.assertRaisesRegex(ValueError, "provider_response_too_large"):
            transport.request("GET", "https://example.invalid/query")
        self.assertTrue(response.closed)

    def test_invalid_content_length_does_not_disable_stream_limit(self) -> None:
        response = FakeResponse(
            chunks=[b"a" * 800, b"b" * 800],
            headers={"Content-Length": "not-a-number"},
        )
        transport = ProviderHttpTransport(session=FakeSession(response), max_response_bytes=1024)

        with self.assertRaisesRegex(ValueError, "provider_response_too_large"):
            transport.request("GET", "https://example.invalid/query")
        self.assertTrue(response.closed)

    def test_response_elapsed_defaults_for_legacy_three_argument_construction(self) -> None:
        response = ProviderHttpResponse(302, {"Location": "/next"}, b"")
        self.assertEqual(response.elapsed_ms, 0)
        self.assertTrue(response.ok)


if __name__ == "__main__":
    unittest.main()
