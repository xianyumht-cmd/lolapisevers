import unittest
from unittest.mock import patch

from services.api_parser_center import ProviderExecution
from services.contact_risk_service import (
    _query_parser_provider,
    format_contact_risk_text,
)


RISK_PROVIDER = {
    "id": "risk-primary",
    "enabled": True,
    "request": {
        "method": "GET",
        "url": "https://risk.example.test/query",
        "query": {
            "account": "$identifier",
            "type": "$identifier_type",
            "token": "$secret:RISK_API_TOKEN",
        },
    },
    "parser": {
        "success": {"path": "code", "op": "eq", "value": 0},
        "outcomes": [
            {
                "name": "hit",
                "when": {"path": "result.risk", "op": "eq", "value": True},
            },
            {
                "name": "clear",
                "when": {"path": "result.risk", "op": "eq", "value": False},
            },
        ],
        "fields": {
            "count": {"paths": ["result.total"]},
        },
        "records": {
            "path": "result.records",
            "fields": {
                "reason": {"paths": ["reason"]},
                "reported_at": {"paths": ["reported_at"]},
                "evidence": {"paths": ["evidence"]},
            },
        },
        "templates": {
            "hit": "发现 {count} 条记录",
            "clear": "暂未发现记录",
        },
    },
}


class ContactRiskParserCenterTests(unittest.IsolatedAsyncioTestCase):
    async def test_parser_provider_extracts_multiple_reasons(self):
        execution = ProviderExecution(
            status_code=200,
            elapsed_ms=30,
            content_type="application/json",
            payload={
                "code": 0,
                "result": {
                    "risk": True,
                    "total": 2,
                    "records": [
                        {"reason": "收款后失联", "reported_at": "2026-07-20"},
                        {"reason": "售卖无效卡密", "reported_at": "2026-07-25"},
                    ],
                },
            },
            text="",
        )
        with patch.dict("os.environ", {"RISK_API_TOKEN": "secret"}, clear=False), patch(
            "services.contact_risk_service.execute_request",
            return_value=execution,
        ):
            result = await _query_parser_provider(RISK_PROVIDER, "qq", "123456")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["hit"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["reports"], ["收款后失联", "售卖无效卡密"])
        self.assertTrue(result["parser_center"])

    def test_public_text_has_details_but_no_provider_identity(self):
        text = format_contact_risk_text(
            {
                "category": "scammer",
                "identifier_type": "qq",
                "identifier_value": "123456",
                "status": "reported",
                "local": None,
                "providers": [
                    {
                        "provider": "risk.example.test",
                        "status": "ok",
                        "hit": True,
                        "count": 2,
                        "message": "",
                        "reports": ["收款后失联", "售卖无效卡密"],
                    }
                ],
            }
        )

        self.assertIn("风险详情", text)
        self.assertIn("收款后失联", text)
        self.assertIn("售卖无效卡密", text)
        self.assertNotIn("risk.example.test", text)
        self.assertNotIn("外部来源", text)
        self.assertNotIn("Provider", text)
        self.assertNotIn("接口来源", text)

    def test_provider_promotional_message_is_not_rendered(self):
        text = format_contact_risk_text(
            {
                "category": "peer",
                "identifier_type": "wechat",
                "identifier_value": "wx_test",
                "status": "reported",
                "local": None,
                "providers": [
                    {
                        "provider": "hidden-provider",
                        "status": "ok",
                        "hit": True,
                        "count": 1,
                        "message": "请访问 https://provider.example 查询详情",
                        "reports": [],
                    }
                ],
            }
        )

        self.assertNotIn("provider.example", text)
        self.assertNotIn("请访问", text)
        self.assertNotIn("hidden-provider", text)


if __name__ == "__main__":
    unittest.main()
