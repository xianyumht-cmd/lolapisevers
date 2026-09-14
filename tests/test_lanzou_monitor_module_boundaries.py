from __future__ import annotations

import inspect
import unittest

from lanzou_update_push_api_server import monitor
from lanzou_update_push_api_server.monitor_diff import compare_snapshots as diff_compare_snapshots
from lanzou_update_push_api_server.monitor_state import StateStore as MonitorStateStore


class LanzouMonitorModuleBoundaryTests(unittest.TestCase):
    def test_legacy_monitor_exports_point_to_owned_modules(self) -> None:
        self.assertIs(monitor.StateStore, MonitorStateStore)
        self.assertIs(monitor.compare_snapshots, diff_compare_snapshots)

    def test_monitor_no_longer_owns_state_store_or_snapshot_diff(self) -> None:
        source = inspect.getsource(monitor)

        self.assertNotIn("class StateStore", source)
        self.assertNotIn("def compare_snapshots(", source)
        self.assertIn("class LanzouMonitorService", source)


if __name__ == "__main__":
    unittest.main()
