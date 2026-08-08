from __future__ import annotations

import unittest

from lanzou_update_push_api_server.control_extensions import _migrated_tab_target
from lanzou_update_push_api_server.control_ui import (
    ASSET_DIRECTORY,
    render_diagnostics_page,
    render_logs_page,
    render_system_page,
)


class _Url:
    def __init__(self, path: str) -> None:
        self.path = path


class _Request:
    def __init__(self, path: str, tab: str = "") -> None:
        self.url = _Url(path)
        self.query_params = {"tab": tab} if tab else {}


class ControlUiOperationsTests(unittest.TestCase):
    def test_operations_pages_use_shared_shell_and_correct_active_navigation(self) -> None:
        cases = (
            (render_logs_page(), "logs", "运行日志", "logRows"),
            (render_diagnostics_page(), "diagnostics", "诊断与修复", "diagnosticRows"),
            (render_system_page(), "system", "安全与回滚", "backupRows"),
        )
        for html, active, title, control in cases:
            with self.subTest(active=active):
                self.assertIn(f'data-console-ui="{active}"', html)
                self.assertIn(title, html)
                self.assertIn(f'id="{control}"', html)
                self.assertIn('/control-assets/operations.css', html)
                self.assertIn('/control-assets/operations.js', html)
                self.assertNotIn('/control-assets/console.js', html)
                self.assertIn('aria-current="page"', html)
                self.assertEqual(html.count('aria-current="page"'), 1)
                self.assertNotIn('href="/legacy-ui"', html)
                self.assertNotIn('旧版控制台', html)

    def test_destructive_operations_use_dialog_not_native_confirm(self) -> None:
        diagnostics = render_diagnostics_page()
        system = render_system_page()
        script = (ASSET_DIRECTORY / "operations.js").read_text(encoding="utf-8")
        for html in (diagnostics, system):
            self.assertIn('id="operationConfirmDialog"', html)
            self.assertIn('id="operationConfirmForm"', html)
        self.assertIn('id="repairStateButton"', diagnostics)
        self.assertIn('id="restartServiceButton"', system)
        self.assertNotIn('confirm(', script)
        self.assertNotIn('alert(', script)
        self.assertNotIn('prompt(', script)

    def test_operation_result_and_security_state_handling_is_explicit(self) -> None:
        script = (ASSET_DIRECTORY / "operations.js").read_text(encoding="utf-8")
        self.assertIn('data?.token_configured', script)
        self.assertIn('result.data?.ok === false', script)
        self.assertIn('repairError', script)
        self.assertIn('rollbackError', script)
        self.assertIn('restartError', script)

    def test_only_migrated_tabs_redirect_to_new_routes(self) -> None:
        self.assertEqual(_migrated_tab_target(_Request("/", "logs")), "/logs")
        self.assertEqual(_migrated_tab_target(_Request("/ui", "diagnostics")), "/diagnostics")
        self.assertEqual(_migrated_tab_target(_Request("/", "system")), "/system")
        self.assertEqual(_migrated_tab_target(_Request("/", "watchers")), "/lanzou/watchers")
        self.assertIsNone(_migrated_tab_target(_Request("/parser-center", "logs")))


if __name__ == "__main__":
    unittest.main()
