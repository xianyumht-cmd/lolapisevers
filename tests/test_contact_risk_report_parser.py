import unittest
from unittest.mock import AsyncMock, patch

from services.api_parser_center import ProviderExecution
from services.contact_risk_report_delivery import (
    _submit_provider,
    format_contact_risk_report_text,
    report_contact_risk,
)


REPORT_PROVIDER = {
    "id": "report-primary",
    "enabled": True,
    "request": {
        "method": "POST",
        "url": "https://report.example.test/api/report",
        "headers": {"Authorization": "$secret:REPORT_API_TOKEN"},
        "json": {
            "account": "$identifier",
            "type": "$identifier_type",
            "reason": "$content",
            "request_id": "$request_id",
        },
    },
    "parser": {
        "success": {"path": "code", "op": "eq", "value": 0},
        "outcomes": [
            {
                "name": "accepted",
                "when": {"path": "data.accepted", "op": "eq", "value": True},
            },
            {
                "name": "rejected",
                "when": {"path": "data.accepted", "op": "eq", "value": False},
            },
        ],
        "fields": {
            "case_id": {"paths": ["data.case_id"]},
            "review_status": {"paths": ["data.status"]},
            "receipt": {"paths": ["data.message"]},
        },
        "templates": {
            "accepted": "案件编号：{case_id}\n审核状态：{review_status}\n回执说明：{receipt}",
            "rejected": "提交未受理：{receipt}",
        },
    },
}


class ContactRiskReportParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_submission_parses_case_status_and_receipt(self):
        execution = ProviderExecution(
            status_code=200,
            elapsed_ms=40,
            content_type="application/json",
            payload={
                "code": 0,
                "data": {
                    "accepted": True,
                    "case_id": "CASE-20260731-001",
                    "status": "pending_review",
                    "message": "举报已提交，等待审核",
                },
            },
            text="",
        )
        parameters = {
            "identifier": "123456",
            "identifier_type": "qq",
            "content": "收款后失联",
            "request_id": "risk-report-001",
        }
        with patch.dict("os.environ", {"REPORT_API_TOKEN": "secret"}, clear=False), patch(
            "services.contact_risk_report_delivery.execute_request",
            return_value=execution,
        ):
            result = await _submit_provider(REPORT_PROVIDER, parameters)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["case_id"], "CASE-20260731-001")
        self.assertEqual(result["review_status"], "pending_review")
        self.assertEqual(result["receipt"], "举报已提交，等待审核")

    async def test_local_save_happens_before_submission_and_duplicate_skips_submit(self):
        local_payload = {
            "category": "scammer",
            "identifier_type": "qq",
            "identifier_value": "123456",
            "duplicate": True,
            "record": {"report_count": 1},
        }
        with patch(
            "services.contact_risk_report_delivery.save_local_contact_risk_report",
            new=AsyncMock(return_value=local_payload),
        ) as local_save, patch(
            "services.contact_risk_report_delivery.load_report_providers",
            return_value=[REPORT_PROVIDER],
        ), patch(
            "services.contact_risk_report_delivery._submit_provider",
            new=AsyncMock(),
        ) as submit:
            result = await report_contact_risk(
                object(),
                request_id="risk-report-001",
                category="scammer",
                identifier_type="qq",
                identifier_value="123456",
                content="收款后失联",
                source="snowluma",
            )

        local_save.assert_awaited_once()
        submit.assert_not_awaited()
        self.assertEqual(result["submission_status"], "skipped_duplicate")

    async def test_failed_online_submission_keeps_local_record(self):
        local_payload = {
            "category": "scammer",
            "identifier_type": "qq",
            "identifier_value": "123456",
            "duplicate": False,
            "record": {"report_count": 1},
        }
        unavailable = {
            "provider": "report-primary",
            "status": "unavailable",
            "outcome": "unavailable",
            "case_id": "",
            "review_status": "",
            "receipt": "",
        }
        with patch(
            "services.contact_risk_report_delivery.save_local_contact_risk_report",
            new=AsyncMock(return_value=local_payload),
        ), patch(
            "services.contact_risk_report_delivery.load_report_providers",
            return_value=[REPORT_PROVIDER],
        ), patch(
            "services.contact_risk_report_delivery._submit_provider",
            new=AsyncMock(return_value=unavailable),
        ):
            result = await report_contact_risk(
                object(),
                request_id="risk-report-002",
                category="scammer",
                identifier_type="qq",
                identifier_value="123456",
                content="收款后失联",
                source="snowluma",
            )

        self.assertEqual(result["record"]["report_count"], 1)
        self.assertEqual(result["submission_status"], "unavailable")
        text = format_contact_risk_report_text(result)
        self.assertIn("本地记录已保留", text)

    async def test_invalid_submission_config_still_returns_local_success(self):
        local_payload = {
            "category": "scammer",
            "identifier_type": "qq",
            "identifier_value": "123456",
            "duplicate": False,
            "record": {"report_count": 1},
        }
        with patch(
            "services.contact_risk_report_delivery.save_local_contact_risk_report",
            new=AsyncMock(return_value=local_payload),
        ) as local_save, patch(
            "services.contact_risk_report_delivery.load_report_providers",
            side_effect=RuntimeError("broken config"),
        ):
            result = await report_contact_risk(
                object(),
                request_id="risk-report-003",
                category="scammer",
                identifier_type="qq",
                identifier_value="123456",
                content="收款后失联",
                source="snowluma",
            )

        local_save.assert_awaited_once()
        self.assertEqual(result["record"]["report_count"], 1)
        self.assertEqual(result["submission_status"], "configuration_error")
        text = format_contact_risk_report_text(result)
        self.assertIn("本地记录已保留", text)
        self.assertNotIn("broken config", text)

    def test_public_report_output_has_receipt_but_no_provider_identity(self):
        text = format_contact_risk_report_text(
            {
                "category": "scammer",
                "identifier_type": "qq",
                "identifier_value": "123456",
                "duplicate": False,
                "record": {"report_count": 1},
                "submission_status": "accepted",
                "submissions": [
                    {
                        "provider": "report.example.test",
                        "status": "ok",
                        "outcome": "accepted",
                        "case_id": "CASE-001",
                        "review_status": "等待审核",
                        "receipt": "举报已受理",
                    }
                ],
            }
        )

        self.assertIn("案件编号：CASE-001", text)
        self.assertIn("审核状态：等待审核", text)
        self.assertIn("回执说明：举报已受理", text)
        self.assertNotIn("report.example.test", text)
        self.assertNotIn("Provider", text)
        self.assertNotIn("接口来源", text)


if __name__ == "__main__":
    unittest.main()
