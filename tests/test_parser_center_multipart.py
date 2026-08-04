import json
import unittest
from pathlib import Path

import requests

from services.api_parser_center import (
    ParserConfigError,
    parse_response,
    prepare_request,
    validate_config,
)
from services.parser_center_multipart import install_parser_center_multipart_support


PROJECT_ROOT = Path(__file__).resolve().parents[1]


PIANZI_PROVIDER = {
    "id": "pianzi-lol-anonymous-report",
    "name": "骗子举报审核入口",
    "enabled": True,
    "request": {
        "method": "POST",
        "url": "https://pianzi.lol/api/anonymous/report",
        "headers": {"X-LAPI-Request-Encoding": "multipart"},
        "form": {
            "report_identity_mode": "anonymous",
            "scammer_qq": "$qq",
            "scammer_name": "",
            "scammer_wechat": "",
            "scammer_phone": "",
            "scammer_idcard": "",
            "fraud_amount": "",
            "incident_at": "",
            "transaction_method": "",
            "report_content": "$content",
            "evidence_notes": "",
        },
        "timeout_seconds": 15,
    },
    "parser": {
        "success": {"path": "success", "op": "eq", "value": True},
        "error_message_paths": ["error", "message"],
        "outcomes": [
            {
                "name": "pending",
                "when": {"path": "success", "op": "eq", "value": True},
            }
        ],
        "default_outcome": "unknown",
        "fields": {
            "review_status": {
                "paths": ["review_status", "status"],
                "default": "等待审核",
                "string": True,
            },
            "receipt": {
                "paths": ["message"],
                "default": "举报已提交，等待审核",
                "string": True,
            },
        },
        "templates": {
            "pending": "审核状态：{review_status}\n回执说明：{receipt}",
            "unknown": "举报提交结果暂无法确认",
        },
    },
}


class ParserCenterMultipartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_parser_center_multipart_support()

    def test_pianzi_request_uses_real_multipart_with_generated_boundary(self):
        prepared = prepare_request(
            PIANZI_PROVIDER,
            {"qq": "12345012", "content": "测试举报"},
        )

        kwargs = prepared.requests_kwargs()
        self.assertIn("files", kwargs)
        self.assertNotIn("data", kwargs)
        self.assertNotIn("json", kwargs)
        self.assertNotIn("X-LAPI-Request-Encoding", kwargs["headers"])

        request_kwargs = {key: value for key, value in kwargs.items() if key != "timeout"}
        wire = requests.Request(
            prepared.method,
            prepared.url,
            **request_kwargs,
        ).prepare()

        content_type = str(wire.headers.get("Content-Type") or "")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        body = wire.body if isinstance(wire.body, bytes) else str(wire.body).encode("utf-8")
        self.assertIn(b'name="scammer_qq"', body)
        self.assertIn(b"12345012", body)
        self.assertIn(b'name="report_content"', body)
        self.assertIn("测试举报".encode("utf-8"), body)
        self.assertIn(b'name="report_identity_mode"', body)
        self.assertIn(b"anonymous", body)

    def test_empty_optional_fields_are_preserved_as_text_parts(self):
        prepared = prepare_request(
            PIANZI_PROVIDER,
            {"qq": "12345012", "content": "测试举报"},
        )
        files = dict(prepared.requests_kwargs()["files"])

        self.assertEqual(files["scammer_name"], (None, ""))
        self.assertEqual(files["fraud_amount"], (None, ""))
        self.assertEqual(files["evidence_notes"], (None, ""))

    def test_internal_selector_is_never_sent_upstream(self):
        prepared = prepare_request(
            PIANZI_PROVIDER,
            {"qq": "12345012", "content": "测试举报"},
        )
        safe = prepared.redacted()
        kwargs = prepared.requests_kwargs()

        self.assertEqual(
            safe["headers"]["X-LAPI-Request-Encoding"],
            "multipart",
        )
        self.assertNotIn("X-LAPI-Request-Encoding", kwargs["headers"])

    def test_manual_multipart_content_type_is_rejected(self):
        provider = json.loads(json.dumps(PIANZI_PROVIDER))
        provider["request"]["headers"]["Content-Type"] = "multipart/form-data"
        prepared = prepare_request(
            provider,
            {"qq": "12345012", "content": "测试举报"},
        )

        with self.assertRaises(ParserConfigError):
            prepared.requests_kwargs()

    def test_success_true_maps_to_pending_review(self):
        parsed = parse_response(
            PIANZI_PROVIDER,
            {"success": True, "message": "举报提交成功，请等待审核"},
            status_code=200,
        )

        self.assertEqual(parsed["outcome"], "pending")
        self.assertEqual(parsed["fields"]["review_status"], "等待审核")
        self.assertEqual(parsed["fields"]["receipt"], "举报提交成功，请等待审核")
        self.assertNotIn("pianzi.lol", parsed["public_text"])

    def test_default_profile_exists_but_does_not_auto_enable(self):
        path = PROJECT_ROOT / "config" / "interface-parser-center.default.json"
        config = validate_config(json.loads(path.read_text(encoding="utf-8")))
        providers = config["features"]["scammer_report"]["providers"]
        provider = next(
            item for item in providers if item.get("id") == "pianzi-lol-anonymous-report"
        )

        self.assertFalse(provider["enabled"])
        self.assertEqual(provider["request"]["method"], "POST")
        self.assertEqual(
            provider["request"]["headers"]["X-LAPI-Request-Encoding"],
            "multipart",
        )

    def test_existing_urlencoded_form_behavior_is_unchanged(self):
        provider = {
            "id": "legacy-form",
            "request": {
                "method": "POST",
                "url": "https://example.test/form",
                "form": {"account": "$qq"},
            },
        }
        prepared = prepare_request(provider, {"qq": "12345012"})
        kwargs = prepared.requests_kwargs()

        self.assertEqual(kwargs["data"], {"account": "12345012"})
        self.assertNotIn("files", kwargs)


if __name__ == "__main__":
    unittest.main()
