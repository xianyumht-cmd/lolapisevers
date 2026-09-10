import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.lol_patch_status import router
from services.lol_patch_schedule_service import get_patch_status


class LolPatchScheduleServiceTests(unittest.TestCase):
    def test_patch_day_is_true_with_deterministic_event_id(self):
        status = get_patch_status(
            "2026-09-10",
            now=datetime(2026, 9, 10, 4, 30, tzinfo=timezone.utc),
        )
        self.assertTrue(status["is_update_today"])
        self.assertEqual(status["patch"], "26.18")
        self.assertEqual(status["event_id"], "lol-patch-26.18-2026-09-10")
        self.assertEqual(status["next_update_date"], "2026-09-23")
        self.assertEqual(status["next_patch"], "26.19")
        self.assertEqual(status["schedule_timezone"], "Asia/Shanghai")
        self.assertTrue(status["checked_at"].endswith("+08:00"))

    def test_non_patch_day_is_false_and_keeps_current_patch(self):
        status = get_patch_status("2026-09-11")
        self.assertFalse(status["is_update_today"])
        self.assertEqual(status["patch"], "26.18")
        self.assertIsNone(status["event_id"])
        self.assertEqual(status["next_update_date"], "2026-09-23")
        self.assertEqual(status["next_patch"], "26.19")

    def test_before_first_known_patch_has_no_current_patch(self):
        status = get_patch_status("2026-01-01")
        self.assertFalse(status["is_update_today"])
        self.assertIsNone(status["patch"])
        self.assertEqual(status["next_update_date"], "2026-01-08")
        self.assertEqual(status["next_patch"], "26.01")

    def test_last_known_patch_has_no_next_patch(self):
        status = get_patch_status("2026-12-09")
        self.assertTrue(status["is_update_today"])
        self.assertEqual(status["patch"], "26.24")
        self.assertIsNone(status["next_update_date"])
        self.assertIsNone(status["next_patch"])

    def test_default_date_uses_asia_shanghai(self):
        status = get_patch_status(
            now=datetime(2026, 9, 9, 16, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(status["date"], "2026-09-10")
        self.assertTrue(status["is_update_today"])
        self.assertEqual(status["patch"], "26.18")

    def test_invalid_date_raises(self):
        with self.assertRaisesRegex(ValueError, "invalid_date"):
            get_patch_status("2026-9-10")


class LolPatchStatusRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    def test_route_contract_shape(self):
        response = self.client.get("/lol/patch-status", params={"date": "2026-09-10"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "date",
                "patch",
                "is_update_today",
                "next_update_date",
                "next_patch",
                "source",
                "source_url",
                "checked_at",
                "event_id",
                "schedule_timezone",
            },
        )
        self.assertEqual(body["patch"], "26.18")
        self.assertTrue(body["is_update_today"])

    def test_route_rejects_malformed_date(self):
        response = self.client.get("/lol/patch-status", params={"date": "not-a-date"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "invalid_date")


if __name__ == "__main__":
    unittest.main()
