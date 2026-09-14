from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.contact_risk_retry_queue import ContactRiskRetryQueue
from services.contact_risk_store import ContactRiskStore


class AppLifecycleBoundaryTests(unittest.TestCase):
    def test_contact_risk_store_constructor_does_not_touch_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "contact-risk.db"
            store = ContactRiskStore(path)
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

            store.start()
            self.assertTrue(path.is_file())

    def test_retry_queue_constructor_does_not_touch_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "retry.db"
            queue = ContactRiskRetryQueue(path)
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

            queue.start()
            self.assertTrue(path.is_file())

    def test_build_app_defers_runtime_resources_to_lifespan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            risk_db = root / "runtime" / "contact-risk.db"
            watch_config = root / "runtime" / "target-file-watch.json"
            watch_state = root / "runtime" / "target-file-watch-state.json"
            with patch.dict(
                os.environ,
                {
                    "CONTACT_RISK_DB_PATH": str(risk_db),
                    "TARGET_FILE_WATCH_CONFIG_PATH": str(watch_config),
                    "TARGET_FILE_WATCH_STATE_PATH": str(watch_state),
                },
                clear=False,
            ):
                from app import build_app

                application = build_app()

            self.assertIsNone(application.state.ctx)
            self.assertIsNone(application.state.so1_client)
            self.assertIsNone(application.state.target_file_watch_service)
            self.assertFalse(risk_db.exists())
            self.assertFalse(watch_config.exists())
            self.assertFalse(watch_state.exists())

    def test_target_file_watch_runtime_has_no_import_time_service_instance(self) -> None:
        import services.target_file_watch_runtime as runtime

        self.assertFalse(hasattr(runtime, "target_file_watch_service"))
        self.assertTrue(callable(runtime.create_target_file_watch_service))


if __name__ == "__main__":
    unittest.main()
