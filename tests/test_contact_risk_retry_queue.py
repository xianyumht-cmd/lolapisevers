import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services.contact_risk_report_delivery import (
    report_contact_risk,
    retry_report_queue,
)
from services.contact_risk_retry_queue import ContactRiskRetryQueue


class ContactRiskRetryQueueTests(unittest.IsolatedAsyncioTestCase):
    def test_queue_persists_and_deduplicates_request_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "risk.db"
            first = ContactRiskRetryQueue(path)
            item1 = first.enqueue(
                request_id="req-1",
                feature="scammer_report",
                provider_id="provider-a",
                parameters={"identifier": "123456", "content": "收款后失联"},
                error_class="TimeoutError",
                delay_seconds=0,
            )
            item2 = first.enqueue(
                request_id="req-1",
                feature="scammer_report",
                provider_id="provider-a",
                parameters={"identifier": "123456", "content": "收款后失联"},
                error_class="ConnectionError",
                delay_seconds=0,
            )
            reopened = ContactRiskRetryQueue(path)
            items = reopened.list(state="pending")

        self.assertEqual(item1["queue_id"], item2["queue_id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["last_error_class"], "ConnectionError")
        self.assertEqual(items[0]["parameters"]["content"], "收款后失联")

    def test_exponential_backoff_and_terminal_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = ContactRiskRetryQueue(Path(temp) / "risk.db")
            item = queue.enqueue(
                request_id="req-2",
                feature="peer_report",
                provider_id="provider-b",
                parameters={"identifier": "wx_test"},
                delay_seconds=0,
            )
            updated = queue.mark_failed(
                item["queue_id"],
                error_class="TimeoutError",
                max_attempts=1,
            )

        self.assertEqual(updated["attempts"], 1)
        self.assertEqual(updated["state"], "failed")

    async def test_failed_submission_is_enqueued_after_local_save(self):
        local_payload = {
            "category": "scammer",
            "identifier_type": "qq",
            "identifier_value": "123456",
            "duplicate": False,
            "record": {"report_count": 1},
        }
        provider = {
            "id": "provider-a",
            "enabled": True,
            "request": {"method": "POST", "url": "https://example.test/report"},
            "parser": {},
        }
        failed = {
            "provider": "provider-a",
            "status": "unavailable",
            "outcome": "unavailable",
            "error_class": "TimeoutError",
        }
        with tempfile.TemporaryDirectory() as temp:
            queue = ContactRiskRetryQueue(Path(temp) / "risk.db")
            with patch(
                "services.contact_risk_report_delivery.save_local_contact_risk_report",
                new=AsyncMock(return_value=local_payload),
            ), patch(
                "services.contact_risk_report_delivery.load_report_providers",
                return_value=[provider],
            ), patch(
                "services.contact_risk_report_delivery._submit_provider",
                new=AsyncMock(return_value=failed),
            ), patch(
                "services.contact_risk_report_delivery.get_contact_risk_retry_queue",
                return_value=queue,
            ):
                result = await report_contact_risk(
                    object(),
                    request_id="req-3",
                    category="scammer",
                    identifier_type="qq",
                    identifier_value="123456",
                    content="收款后失联",
                    source="snowluma",
                )
            items = queue.list(state="pending")

        self.assertEqual(result["queued_submission_count"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["provider_id"], "provider-a")
        self.assertNotIn("https://example.test", str(items[0]))

    async def test_manual_retry_marks_success(self):
        provider = {
            "id": "provider-a",
            "enabled": True,
            "request": {"method": "POST", "url": "https://example.test/report"},
            "parser": {},
        }
        success = {
            "provider": "provider-a",
            "status": "ok",
            "outcome": "accepted",
            "case_id": "CASE-1",
            "review_status": "pending",
            "receipt": "已受理",
        }
        with tempfile.TemporaryDirectory() as temp:
            queue = ContactRiskRetryQueue(Path(temp) / "risk.db")
            item = queue.enqueue(
                request_id="req-4",
                feature="scammer_report",
                provider_id="provider-a",
                parameters={"identifier": "123456", "content": "证据"},
                delay_seconds=0,
            )
            config = {
                "schema": "lapi-parser-center.v1",
                "features": {
                    "scammer_report": {
                        "operation": "report",
                        "providers": [provider],
                    }
                },
            }
            with patch(
                "services.contact_risk_report_delivery.get_contact_risk_retry_queue",
                return_value=queue,
            ), patch(
                "services.contact_risk_report_delivery.load_config",
                return_value=config,
            ), patch(
                "services.contact_risk_report_delivery._submit_provider",
                new=AsyncMock(return_value=success),
            ):
                result = await retry_report_queue(queue_id=item["queue_id"])
            completed = queue.list(state="completed")

        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(completed), 1)


if __name__ == "__main__":
    unittest.main()
