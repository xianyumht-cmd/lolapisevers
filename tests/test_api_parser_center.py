import os
import unittest
from unittest.mock import patch

from services.api_parser_center import (
    ParserConfigError,
    parse_response,
    prepare_request,
    redact,
    render_template,
    to_lolban_payload,
    validate_config,
    validate_public_template,
)


LOLBAN_PROVIDER = {
    "id": "lolban-primary",
    "enabled": True,
    "request": {
        "method": "GET",
        "url": "http://q.lolmap.cn/api/query.html",
        "query": {
            "qq": "$qq",
            "token": "$secret:LOLMAP_API_TOKEN",
        },
        "timeout_seconds": 10,
    },
    "parser": {
        "success": {"path": "code", "op": "eq", "value": 200},
        "outcomes": [
            {
                "name": "hit",
                "when": {"path": "data.status", "op": "eq", "value": "封禁"},
            },
            {
                "name": "clear",
                "when": {"path": "data.status", "op": "eq", "value": "正常"},
            },
        ],
        "fields": {
            "qq": {"paths": ["data.qq"], "required": True, "string": True},
            "status": {"paths": ["data.status"], "required": True, "string": True},
            "ban_time": {"paths": ["data.ban_time"], "string": True},
            "end_time": {"paths": ["data.end_time"], "string": True},
            "ban_reason": {
                "paths": ["data.ban_reason", "data.reason"],
                "default": "第三方接口未提供封禁原因",
                "string": True,
            },
        },
        "templates": {
            "hit": "账号封禁查询结果\n\nQQ号码：{qq}\n账号状态：{status}\n封禁原因：{ban_reason}\n封禁时间：{ban_time}\n剩余时间：{end_time}",
            "clear": "账号封禁查询结果\n\nQQ号码：{qq}\n账号状态：{status}",
        },
    },
}


class ApiParserCenterTests(unittest.TestCase):
    def test_lolban_reason_is_preserved_without_provider_promotion(self):
        response = {
            "code": 200,
            "by": "q.lolmap.cn",
            "data": {
                "qq": "97077000",
                "ban_time": "2031-1-2 14:03:37",
                "end_time": "1987天2小时32分41秒",
                "ban_reason": "游戏环境异常：检测到违规软件加载",
                "status": "封禁",
            },
            "msg": "此账号已被封禁",
        }

        parsed = parse_response(LOLBAN_PROVIDER, response, status_code=200)
        normalized = to_lolban_payload("97077000", parsed)

        self.assertEqual(parsed["outcome"], "hit")
        self.assertEqual(
            normalized["data"]["ban_reason"],
            "游戏环境异常：检测到违规软件加载",
        )
        self.assertIn(
            "封禁原因：游戏环境异常：检测到违规软件加载",
            normalized["public_text"],
        )
        self.assertNotIn("q.lolmap.cn", normalized["public_text"])
        self.assertNotIn("接口来源", normalized["public_text"])
        self.assertNotIn("Provider", normalized["public_text"])
        self.assertEqual(normalized["by"], "configured-provider")

    def test_secret_reference_is_server_side_and_redacted(self):
        with patch.dict(os.environ, {"LOLMAP_API_TOKEN": "top-secret-token"}, clear=False):
            prepared = prepare_request(LOLBAN_PROVIDER, {"qq": "97077000"})

        self.assertEqual(prepared.query["token"], "top-secret-token")
        safe = prepared.redacted()
        self.assertEqual(safe["query"]["token"], "***")
        self.assertNotIn("top-secret-token", str(safe))

    def test_record_array_parser_supports_custom_fields(self):
        provider = {
            "id": "risk-query",
            "request": {"method": "GET", "url": "https://example.test/query"},
            "parser": {
                "success": {"path": "code", "op": "eq", "value": 0},
                "outcomes": [
                    {
                        "name": "hit",
                        "when": {"path": "result.risk", "op": "eq", "value": True},
                    }
                ],
                "fields": {
                    "账号": {"paths": ["result.account"]},
                    "记录数量": {"paths": ["result.total"]},
                },
                "records": {
                    "path": "result.records",
                    "fields": {
                        "原因": {"paths": ["reason"]},
                        "时间": {"paths": ["reported_at"]},
                        "证据": {"paths": ["evidence"]},
                    },
                },
                "templates": {
                    "hit": "账号：{账号}\n累计记录：{记录数量}\n{{#records}}第 {序号} 条\n原因：{原因}\n时间：{时间}\n证据：{证据|未提供}\n{{/records}}",
                },
            },
        }
        payload = {
            "code": 0,
            "result": {
                "account": "123456",
                "risk": True,
                "total": 2,
                "records": [
                    {"reason": "收款后拉黑", "reported_at": "2026-07-20"},
                    {"reason": "售卖无效卡密", "reported_at": "2026-07-25"},
                ],
            },
        }

        parsed = parse_response(provider, payload)

        self.assertEqual(len(parsed["records"]), 2)
        self.assertIn("第 1 条", parsed["public_text"])
        self.assertIn("收款后拉黑", parsed["public_text"])
        self.assertIn("售卖无效卡密", parsed["public_text"])

    def test_public_template_rejects_source_fields_and_literal_domain(self):
        with self.assertRaises(ParserConfigError):
            validate_public_template("接口来源：{provider}")
        with self.assertRaises(ParserConfigError):
            validate_public_template(
                "来源 q.lolmap.cn",
                provider_url="http://q.lolmap.cn/api/query.html",
            )

    def test_config_validation_keeps_disabled_provider(self):
        config = {
            "schema": "lapi-parser-center.v1",
            "features": {
                "lolban": {
                    "operation": "query",
                    "providers": [{**LOLBAN_PROVIDER, "enabled": False}],
                }
            },
        }

        normalized = validate_config(config)

        self.assertFalse(normalized["features"]["lolban"]["providers"][0]["enabled"])

    def test_redaction_handles_nested_authorization_and_query_token(self):
        safe = redact(
            {
                "headers": {"Authorization": "Bearer secret"},
                "url": "https://example.test/query?qq=1&token=secret",
            }
        )

        self.assertEqual(safe["headers"]["Authorization"], "***")
        self.assertIn("token=%2A%2A%2A", safe["url"])
        self.assertNotIn("secret", str(safe))

    def test_redaction_fails_closed_for_malformed_url(self):
        safe = redact({"url": "https://[broken?token=top-secret-token"})
        self.assertEqual(safe["url"], "***")
        self.assertNotIn("top-secret-token", str(safe))

    def test_template_defaults(self):
        rendered = render_template("原因：{reason|未提供}", {}, [])
        self.assertEqual(rendered, "原因：未提供")


if __name__ == "__main__":
    unittest.main()
