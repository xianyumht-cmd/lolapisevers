from __future__ import annotations

import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from services.api_parser_center import execute_request, prepare_request
from services.dynamic_query_service import DynamicProviderDefinition
from services.parser_center_multipart import install_parser_center_multipart_support
from services.provider_http_transport import ProviderHttpResponse
from services import dynamic_query_service


class RecordingTransport:
    def __init__(self, response: ProviderHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class ProviderTransportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_parser_center_multipart_support()

    def test_parser_center_executes_through_bounded_standard_transport(self) -> None:
        prepared = prepare_request(
            {
                "id": "standard",
                "request": {
                    "method": "POST",
                    "url": "https://example.test/query",
                    "headers": {"X-Test": "1"},
                    "query": {"qq": "$qq"},
                    "form": {"mode": "query"},
                    "timeout_seconds": 7,
                },
            },
            {"qq": "123456"},
        )
        transport = RecordingTransport(
            ProviderHttpResponse(
                200,
                {"Content-Type": "application/json; charset=utf-8"},
                b'{"ok":true}',
                17,
            )
        )

        result = execute_request(prepared, transport=transport)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.elapsed_ms, 17)
        self.assertEqual(result.content_type, "application/json; charset=utf-8")
        self.assertEqual(result.payload, {"ok": True})
        kwargs = transport.calls[0][2]
        self.assertEqual(kwargs["headers"], {"X-Test": "1"})
        self.assertEqual(kwargs["params"], {"qq": "123456"})
        self.assertEqual(kwargs["data"], {"mode": "query"})
        self.assertEqual(kwargs["timeout_seconds"], 7.0)
        self.assertFalse(kwargs["allow_redirects"])

    def test_parser_center_keeps_multipart_encoding_on_standard_transport(self) -> None:
        prepared = prepare_request(
            {
                "id": "multipart",
                "request": {
                    "method": "POST",
                    "url": "https://example.test/report",
                    "headers": {"X-LAPI-Request-Encoding": "multipart"},
                    "form": {"qq": "$qq", "content": "$content", "empty": ""},
                    "timeout_seconds": 15,
                },
            },
            {"qq": "123456", "content": "证据"},
        )
        transport = RecordingTransport(
            ProviderHttpResponse(200, {"content-type": "application/json"}, b'{"success":true}', 9)
        )

        execute_request(prepared, transport=transport)

        kwargs = transport.calls[0][2]
        self.assertNotIn("X-LAPI-Request-Encoding", kwargs["headers"])
        self.assertIsNone(kwargs["data"])
        self.assertIsNone(kwargs["json_body"])
        self.assertEqual(
            dict(kwargs["files"]),
            {
                "qq": (None, "123456"),
                "content": (None, "证据"),
                "empty": (None, ""),
            },
        )
        self.assertFalse(kwargs["allow_redirects"])

    def test_dynamic_allow_private_uses_standard_transport(self) -> None:
        definition = DynamicProviderDefinition(
            command_id="private.demo",
            method="POST",
            url="http://127.0.0.1:8080/query",
            headers={"X-Test": "1"},
            query={},
            body={"value": "$value"},
            timeout_ms=2500,
            text_path="",
            response_template="",
            fallback_text="failed",
            snapshot_seconds=0,
            allow_private=True,
        )
        expected = ProviderHttpResponse(200, {}, b"ok", 5)
        with patch.object(
            dynamic_query_service,
            "_validate_destination",
            return_value=(urlsplit(definition.url), "127.0.0.1"),
        ), patch.object(
            dynamic_query_service._private_provider_transport,
            "request",
            return_value=expected,
        ) as request_call:
            result = dynamic_query_service._request_once(
                definition,
                definition.url,
                {"X-Test": "1"},
                {"value": "abc"},
                2.5,
            )

        self.assertIs(result, expected)
        request_call.assert_called_once_with(
            "POST",
            definition.url,
            headers={"X-Test": "1"},
            json_body={"value": "abc"},
            timeout_seconds=2.5,
            allow_redirects=False,
        )

    def test_dynamic_public_provider_keeps_dns_pinned_transport(self) -> None:
        definition = DynamicProviderDefinition(
            command_id="public.demo",
            method="GET",
            url="http://provider.example/data",
            headers={},
            query={},
            body={},
            timeout_ms=1000,
            text_path="",
            response_template="",
            fallback_text="failed",
            snapshot_seconds=0,
            allow_private=False,
        )

        class PoolResponse:
            status = 200
            headers = {}

            def read(self, amount, decode_content=True):
                del amount, decode_content
                return b"ok"

            def release_conn(self):
                return None

        pool = Mock()
        pool.urlopen.return_value = PoolResponse()
        with patch.object(
            dynamic_query_service,
            "_validate_destination",
            return_value=(urlsplit(definition.url), "93.184.216.34"),
        ), patch(
            "services.dynamic_query_service.urllib3.HTTPConnectionPool",
            return_value=pool,
        ) as pool_factory, patch.object(
            dynamic_query_service._private_provider_transport,
            "request",
            side_effect=AssertionError("standard transport must not handle public dynamic providers"),
        ):
            result = dynamic_query_service._request_once(
                definition,
                definition.url,
                {},
                {},
                1.0,
            )

        pool_factory.assert_called_once_with("93.184.216.34", 80, maxsize=1, block=True)
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "provider.example")
        self.assertEqual(result.body, b"ok")


if __name__ == "__main__":
    unittest.main()
