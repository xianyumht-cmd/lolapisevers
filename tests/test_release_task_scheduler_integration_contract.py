import unittest

from lanzou_update_push_api_server import release_task_scheduler as scheduler
from lanzou_update_push_api_server import release_update_guard as guard


class ReleaseTaskSchedulerIntegrationContractTests(unittest.TestCase):
    def test_guard_installs_scheduler_proxy_on_controller(self):
        self.assertIsInstance(
            guard.controller.subprocess,
            scheduler.SchedulerSubprocessProxy,
        )


if __name__ == "__main__":
    unittest.main()
