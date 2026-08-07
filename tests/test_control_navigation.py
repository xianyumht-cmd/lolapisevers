from __future__ import annotations

import unittest

from lanzou_update_push_api_server.control_extensions import _decorate_control_page
from lanzou_update_push_api_server.control_navigation import (
    apply_control_navigation,
    select_parser_center_section,
)
from lanzou_update_push_api_server.control_ui import render_overview_page
from lanzou_update_push_api_server.lolban_console import render_lolban_console_page
from lanzou_update_push_api_server.parser_center_ui_guard import render_parser_center_page
from lanzou_update_push_api_server.server import _control_page


class ControlNavigationTests(unittest.TestCase):
    def test_root_dashboard_uses_new_standalone_console_shell(self):
        page = render_overview_page()
        self.assertIn('data-console-ui="p0"', page)
        self.assertIn('class="sidebar"', page)
        self.assertIn('class="topbar"', page)
        self.assertIn('接口与解析中心', page)
        self.assertIn('/parser-center/secrets', page)
        self.assertIn('/query-console/lolban', page)
        self.assertIn('/main-config', page)
        self.assertIn('/logs', page)
        self.assertIn('/target-file-watch', page)
        self.assertIn('定向文件监控', page)
        self.assertNotIn('/legacy-ui', page)
        self.assertNotIn('旧版入口', page)
        self.assertNotIn('旧版控制台', page)
        self.assertNotIn('control-navigation-style', page)

    def test_root_is_not_wrapped_by_legacy_navigation_injector(self):
        old_page = _control_page()
        self.assertEqual(_decorate_control_page('/', old_page), old_page)

    def test_parser_center_is_wrapped_without_losing_real_actions(self):
        raw = render_parser_center_page()
        page = _decorate_control_page("/parser-center", raw)
        self.assertIn('class="control-sidebar"', page)
        self.assertIn('/admin/parser-center/secret', page)
        self.assertIn('/admin/parser-center/test', page)
        self.assertIn('/admin/parser-center/rollback', page)
        self.assertIn('/target-file-watch', page)
        self.assertIn('定向文件监控', page)
        self.assertIn('Secret 配置', page)
        self.assertIn('请求并解析', page)

    def test_lolban_page_keeps_provider_tokens_inside_provider_cards(self):
        raw = render_lolban_console_page()
        page = _decorate_control_page("/query-console/lolban", raw)
        self.assertIn('data-secret-provider', page)
        self.assertIn('providerSecrets', page)
        self.assertIn('/admin/query-console/lolban/provider-secret', page)
        self.assertIn('providerSecretControl', page)
        self.assertNotIn('id="fourPngSecretPanel"', page)
        self.assertIn('class="control-sidebar"', page)
        self.assertIn('/target-file-watch', page)

    def test_parser_secret_section_is_server_selected(self):
        raw = render_parser_center_page()
        page = select_parser_center_section(raw, "backups")
        self.assertIn('<button class="active" data-tab="backups">', page)
        self.assertIn('<section id="tab-backups" class="tab-panel">', page)
        self.assertIn('<section id="tab-visual" class="tab-panel hidden">', page)

    def test_navigation_does_not_depend_on_css_escape(self):
        page = apply_control_navigation(
            '<!doctype html><html><head></head><body><main class="shell"></main></body></html>',
            active="overview",
        )
        self.assertIn('findSidebarLink', page)
        self.assertNotIn('CSS.escape', page)

    def test_navigation_injection_is_idempotent(self):
        raw = '<!doctype html><html><head></head><body><main class="shell"></main></body></html>'
        first = apply_control_navigation(raw, active="overview")
        second = apply_control_navigation(first, active="overview")
        self.assertEqual(first, second)
        self.assertEqual(first.count('id="control-navigation-style"'), 1)


if __name__ == "__main__":
    unittest.main()
