import base64
import hashlib
import unittest
from unittest.mock import Mock

import requests

from clients.channel_neutral_query_client import (
    IntranetQueryClient,
    QueryClientError,
    normalize_intranet_base_url,
    parse_delivery_envelope,
)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.content = b"{}"
        self.headers = {}
        self.closed = False

    def json(self):
        return self._body

    def close(self):
        self.closed = True


class ChannelNeutralQueryClientTests(unittest.TestCase):
    def test_base_url_allows_lan_and_rejects_public_hosts(self):
        self.assertEqual(normalize_intranet_base_url("http://192.168.3.100:5001/"), "http://192.168.3.100:5001")
        self.assertEqual(normalize_intranet_base_url("http://loldata:5001"), "http://loldata:5001")
        with self.assertRaises(QueryClientError):
            normalize_intranet_base_url("https://api.example.com")
        with self.assertRaises(QueryClientError):
            normalize_intranet_base_url("http://192.168.3.100:5001/api/v1/groupguard/query")

    def test_query_posts_only_feature_parameters_and_capabilities(self):
        response = FakeResponse(
            {
                "protocol": "groupguard-query-delivery.v1",
                "ok": True,
                "feature": "shard",
                "request_id": "server-1",
                "client_request_id": "client-1",
                "delivery": {
                    "kind": "segments",
                    "segments": [{"type": "text", "text": "最终合集结果"}],
                },
                "error": None,
                "retry": {"allowed": False, "after_seconds": 0},
                "meta": {"source": "live"},
            }
        )
        session = Mock(spec=requests.Session)
        session.post.return_value = response
        client = IntranetQueryClient(
            "http://192.168.3.100:5001",
            session=session,
            client_name="official-bot",
        )
        envelope = client.query(
            "shard",
            {"hero": "滑板鞋"},
            preferred="text",
            request_id="client-1",
        )
        self.assertEqual(envelope.text(), "最终合集结果")
        self.assertEqual(envelope.feature, "shard")
        kwargs = session.post.call_args.kwargs
        self.assertEqual(kwargs["json"]["feature"], "shard")
        self.assertEqual(kwargs["json"]["parameters"], {"hero": "滑板鞋"})
        self.assertEqual(kwargs["json"]["client"], "official-bot")
        serialized = str(kwargs["json"])
        self.assertNotIn("github", serialized.lower())
        self.assertNotIn("provider", serialized.lower())
        self.assertTrue(response.closed)

    def test_report_uses_shared_write_endpoint_and_stable_request_id(self):
        response = FakeResponse(
            {
                "protocol": "groupguard-query-delivery.v1",
                "ok": True,
                "feature": "scammer_report",
                "request_id": "server-report-1",
                "client_request_id": "official-message-99",
                "delivery": {
                    "kind": "segments",
                    "segments": [{"type": "text", "text": "举报已收录"}],
                },
                "error": None,
                "retry": {"allowed": False, "after_seconds": 0},
                "meta": {"duplicate": False, "report_count": 1},
            }
        )
        session = Mock(spec=requests.Session)
        session.post.return_value = response
        client = IntranetQueryClient("http://10.0.0.8:5001", session=session, write_token="write-secret")
        envelope = client.report(
            "scammer_report",
            {"identifier_type": "qq", "identifier": "123456", "content": "收款后失联"},
            request_id="official-message-99",
        )
        self.assertEqual(envelope.text(), "举报已收录")
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "http://10.0.0.8:5001/api/v1/groupguard/report")
        self.assertEqual(kwargs["json"]["request_id"], "official-message-99")
        self.assertFalse(kwargs["json"]["capabilities"]["image"])
        self.assertEqual(kwargs["headers"]["X-GroupGuard-Token"], "write-secret")

    def test_report_rejects_blank_and_lossy_request_ids(self):
        client = IntranetQueryClient("http://10.0.0.8:5001", session=Mock(spec=requests.Session))
        with self.assertRaises(QueryClientError) as blank:
            client.report("scammer_report", {"qq": "123456", "content": "证据"}, request_id="")
        self.assertEqual(blank.exception.code, "report_request_id_required")
        with self.assertRaises(QueryClientError) as invalid:
            client.report("scammer_report", {"qq": "123456", "content": "证据"}, request_id="a b")
        self.assertEqual(invalid.exception.code, "invalid_request_id")

    def test_feature_alias_is_canonicalized_before_round_trip(self):
        response = FakeResponse({
            "protocol": "groupguard-query-delivery.v1", "ok": True, "feature": "lolban",
            "request_id": "server-alias-1", "client_request_id": "client-alias-1",
            "delivery": {"kind": "segments", "segments": [{"type": "text", "text": "结果"}]},
            "error": None, "retry": {"allowed": False, "after_seconds": 0}, "meta": {}
        })
        session = Mock(spec=requests.Session)
        session.post.return_value = response
        client = IntranetQueryClient("http://10.0.0.8:5001", session=session)
        envelope = client.query("ban", {"qq": "123456"}, request_id="client-alias-1")
        self.assertEqual(envelope.feature, "lolban")
        self.assertEqual(session.post.call_args.kwargs["json"]["feature"], "lolban")

    def test_image_segment_is_hash_verified_before_channel_delivery(self):
        image = b"fake-png-body"
        encoded = base64.b64encode(image).decode("ascii")
        body = {
            "protocol": "groupguard-query-delivery.v1",
            "ok": True,
            "feature": "battle",
            "request_id": "server-image-1",
            "client_request_id": "client-image-1",
            "delivery": {
                "kind": "segments",
                "segments": [
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "encoding": "base64",
                        "data": encoded,
                        "filename": "battle.png",
                        "bytes": len(image),
                        "sha256": hashlib.sha256(image).hexdigest(),
                    }
                ],
            },
            "error": None,
            "retry": {"allowed": False, "after_seconds": 0},
            "meta": {},
        }
        envelope = parse_delivery_envelope(body, expected_feature="battle")
        self.assertEqual(envelope.images()[0].data, image)
        body["delivery"]["segments"][0]["sha256"] = "0" * 64
        with self.assertRaises(QueryClientError):
            parse_delivery_envelope(body, expected_feature="battle")

    def test_forward_delivery_is_channel_neutral_text_nodes(self):
        envelope = parse_delivery_envelope(
            {
                "protocol": "groupguard-query-delivery.v1",
                "ok": True,
                "feature": "dynamic",
                "request_id": "server-forward-1",
                "client_request_id": "client-forward-1",
                "delivery": {
                    "kind": "forward",
                    "segments": [
                        {
                            "type": "forward",
                            "nodes": [
                                {"segments": [{"type": "text", "text": "第一页"}]},
                                {"segments": [{"type": "text", "text": "第二页"}]},
                            ],
                        }
                    ],
                },
                "error": None,
                "retry": {"allowed": False, "after_seconds": 0},
                "meta": {},
            },
            expected_feature="dynamic",
        )
        self.assertEqual(envelope.text(), "第一页\n\n第二页")

    def test_error_envelope_exposes_only_safe_retry_information(self):
        with self.assertRaises(QueryClientError) as caught:
            parse_delivery_envelope(
                {
                    "protocol": "groupguard-query-delivery.v1",
                    "ok": False,
                    "feature": "video",
                    "request_id": "server-error-1",
                    "client_request_id": "client-error-1",
                    "delivery": {
                        "kind": "segments",
                        "segments": [{"type": "text", "text": "视频查询暂不可用"}],
                    },
                    "error": {
                        "code": "temporarily_unavailable",
                        "user_message": "视频查询暂不可用",
                        "retryable": True,
                    },
                    "retry": {"allowed": True, "after_seconds": 30},
                    "meta": {},
                },
                expected_feature="video",
            )
        self.assertEqual(caught.exception.code, "temporarily_unavailable")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after_seconds, 30)
        self.assertNotIn("http", caught.exception.user_message.lower())


if __name__ == "__main__":
    unittest.main()
