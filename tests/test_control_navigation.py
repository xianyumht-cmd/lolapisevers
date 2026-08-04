from __future__ import annotations

import unittest

from lanzou_update_push_api_server.control_extensions import _decorate_control_page
from lanzou_update_push_api_server.control_navigation import apply_control_navigation
from lanzou_update_push_api_server.lolban_console import render_lolban_console_page
from lanzou_update_push_api_server.parser_center_ui_guard import render_parser_center_page
from lanzou_update_push_api_server.server import _control_page


class ControlNavigationTests(unittest.TestCase):
    def test_root_dashboard_has_professional_sidebar_and_query_entries(self):
        page = _decorate_control_page("/", _control_page())
        self.assertIn('class="control-sidebar"', page)
        self.assertIn('接口与解析中心', page)
        self.assertIn('/parser-center?section=backups', page)
        self.assertIn('/query-console/lolban', page)
        self.assertIn('/?tab=mainconfig', page)
        self.assertIn('/?tab=logs', page)
        self.assertIn('control-original-tabs', page)

    def test_parser_center_is_wrapped_without_losing_real_actions(self):
        raw = render_parser_center_page()
        page = _decorate_control_page("/parser-center", raw)
        self.assertIn('class="control-sidebar"', page)
        self.assertIn('/admin/parser-center/secret', page)
        self.assertIn('/admin/parser-center/test', page)
        self.assertIn('/admin/parser-center/rollback', page)
        self.assertIn('Secret 配置', page)
        self.assertIn('请求并解析', page)

    def test_lolban_page_has_direct_secure_4png_secret_control(self):
        raw = render_lolban_console_page()
        page = _decorate_control_page("/query-console/lolban", raw)
        self.assertIn('4PNG Token', page)
        self.assertIn('LOL_BAN_4PNG_TOKEN', page)
        self.assertIn('/admin/parser-center/secret', page)
        self.assertIn('安全保存 Token', page)
        self.assertIn('class="control-sidebar"', page)

    def test_navigation_injection_is_idempotent(self):
        raw = '<!doctype html><html><head></head><body><main class="shell"></main></body></html>'
        first = apply_control_navigation(raw, active="overview")
        second = apply_control_navigation(first, active="overview")
        self.assertEqual(first, second)
        self.assertEqual(first.count('id="control-navigation-style"'), 1)


if __name__ == "__main__":
    unittest.main()
