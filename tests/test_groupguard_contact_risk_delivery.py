import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from routers.groupguard_delivery import groupguard_query, groupguard_report
from services.contact_risk_store import ContactRiskStore
from services.query_delivery import DELIVERY_PROTOCOL


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


def request_with_store(store):
    ctx = SimpleNamespace(contact_risk_store=store, upstream_http_client=object())
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


class GroupGuardContactRiskDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ContactRiskStore(Path(self.temp.name) / "contact-risk.db")
        self.env = patch.dict(
            os.environ,
            {
                "QUERY_SCAMMER_PROVIDERS_JSON": "",
                "QUERY_PEER_PROVIDERS_JSON": "",
                # Candidate deployment tests run inside the production service
                # environment. Explicitly remove write-token requirements so
                # these service-behaviour tests remain deterministic and do not
                # depend on production credentials. Authentication itself is
                # covered separately by test_control_security.py.
                "GROUPGUARD_WRITE_TOKEN": "",
                "WEBUI_ADMIN_TOKEN": "",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    async def test_empty_store_returns_final_no_record_text_without_claiming_absolute_safety(self):
        response = await groupguard_query(
            request_with_store(self.store),
            {
                "feature": "scammer",
                "parameters": {"identifier_type": "qq", "identifier": "123456"},
                "preferred": "text",
                "request_id": "risk-query-001",
            },
        )
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
        self.assertEqual(body["feature"], "scammer")
        text = body["delivery"]["segments"][0]["text"]
        self.assertIn("暂未发现已收录风险记录", text)
        self.assertIn("不等于绝对安全", text)
        self.assertNotIn("安全账号", text)
        self.assertEqual(body["meta"]["local_report_count"], 0)

    async def test_report_is_immediately_queryable_and_idempotent_by_request_id(self):
        request = request_with_store(self.store)
        payload = {
            "feature": "scammer_report",
            "parameters": {
                "identifier_type": "qq",
                "identifier": "123456",
                "content": "收款后失联",
                "group_id": "10001",
                "actor_id": "20002",
            },
            "preferred": "text",
            "request_id": "risk-report-001",
            "client": "snowluma",
        }
        first = decode(await groupguard_report(request, payload))
        second = decode(await groupguard_report(request, payload))
        self.assertTrue(first["ok"])
        self.assertFalse(first["meta"]["duplicate"])
        self.assertEqual(first["meta"]["report_count"], 1)
        self.assertTrue(second["ok"])
        self.assertTrue(second["meta"]["duplicate"])
        self.assertEqual(second["meta"]["report_count"], 1)

        query = decode(
            await groupguard_query(
                request,
                {
                    "feature": "查骗子",
                    "parameters": {"qq": "123456"},
                    "preferred": "text",
                },
            )
        )
        self.assertEqual(query["meta"]["status"], "reported")
        self.assertEqual(query["meta"]["local_report_count"], 1)
        text = query["delivery"]["segments"][0]["text"]
        self.assertIn("收款后失联", text)

    async def test_same_request_id_with_different_report_is_rejected(self):
        request = request_with_store(self.store)
        first = await groupguard_report(request, {
            "feature": "scammer_report",
            "parameters": {"qq": "11111", "content": "第一条"},
            "request_id": "collision-001",
        })
        second = await groupguard_report(request, {
            "feature": "scammer_report",
            "parameters": {"qq": "22222", "content": "第二条"},
            "request_id": "collision-001",
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertIsNone(self.store.get("scammer", "qq", "22222", touch=False))

    async def test_read_does_not_change_updated_at(self):
        request = request_with_store(self.store)
        await groupguard_report(request, {
            "feature": "scammer_report",
            "parameters": {"qq": "123456", "content": "证据"},
            "request_id": "updated-at-001",
        })
        before = self.store.get("scammer", "qq", "123456", touch=False)
        self.store.get("scammer", "qq", "123456", touch=True)
        after = self.store.get("scammer", "qq", "123456", touch=False)
        self.assertEqual(before["updated_at"], after["updated_at"])
        self.assertNotEqual(before["last_checked_at"], after["last_checked_at"])

    async def test_scammer_and_peer_records_are_isolated(self):
        request = request_with_store(self.store)
        await groupguard_report(
            request,
            {
                "feature": "peer_report",
                "parameters": {
                    "identifier_type": "wechat",
                    "identifier": "wx_peer_01",
                    "content": "同行记录",
                },
                "request_id": "peer-report-001",
                "preferred": "text",
            },
        )
        peer = decode(
            await groupguard_query(
                request,
                {
                    "feature": "peer",
                    "parameters": {"wechat": "wx_peer_01"},
                    "preferred": "text",
                },
            )
        )
        scammer = decode(
            await groupguard_query(
                request,
                {
                    "feature": "scammer",
                    "parameters": {"wechat": "wx_peer_01"},
                    "preferred": "text",
                },
            )
        )
        self.assertEqual(peer["meta"]["status"], "reported")
        self.assertEqual(peer["meta"]["local_report_count"], 1)
        self.assertEqual(scammer["meta"]["status"], "no_record")
        self.assertEqual(scammer["meta"]["local_report_count"], 0)

    async def test_report_requires_request_id_and_valid_identifier(self):
        missing_id = await groupguard_report(
            request_with_store(self.store),
            {
                "feature": "scammer_report",
                "parameters": {"qq": "123456", "content": "证据"},
            },
        )
        self.assertEqual(missing_id.status_code, 400)
        self.assertIn("request_id", decode(missing_id)["error"]["user_message"])

        invalid = await groupguard_query(
            request_with_store(self.store),
            {
                "feature": "peer",
                "parameters": {"identifier_type": "wechat", "identifier": "@@"},
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("微信号", decode(invalid)["error"]["user_message"])

    async def test_response_does_not_expose_database_path_or_provider_configuration(self):
        response = await groupguard_query(
            request_with_store(self.store),
            {
                "feature": "scammer",
                "parameters": {"qq": "123456"},
                "preferred": "text",
            },
        )
        raw = bytes(response.body).decode("utf-8")
        self.assertNotIn(str(self.store.path), raw)
        self.assertNotIn("QUERY_SCAMMER_PROVIDERS_JSON", raw)
        self.assertNotIn("contact_risk.db", raw)


if __name__ == "__main__":
    unittest.main()
