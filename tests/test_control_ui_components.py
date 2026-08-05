from __future__ import annotations

import inspect
import unittest

from lanzou_update_push_api_server.control_ui import pages
from lanzou_update_push_api_server.control_ui.components import (
    icon,
    nav_link,
    render_admin_token_dialog,
    render_console_shell,
    render_sidebar,
)


class ControlUiComponentTests(unittest.TestCase):
    def test_navigation_marks_only_requested_entry_active(self) -> None:
        sidebar = render_sidebar(active="lolban")
        self.assertIn('href="/query-console/lolban" class="nav-link is-active" aria-current="page"', sidebar)
        self.assertEqual(sidebar.count('aria-current="page"'), 1)
        self.assertIn('href="/" class="nav-link"', sidebar)

    def test_legacy_console_is_not_advertised_in_production_navigation(self) -> None:
        sidebar = render_sidebar(active="overview")
        shell = render_console_shell(
            active="overview",
            title="控制台总览",
            content='<section id="content">ok</section>',
            body_marker="test",
        )
        self.assertNotIn('旧版控制台', sidebar)
        self.assertNotIn('旧版入口', shell)
        self.assertNotIn('href="/legacy-ui"', shell)

    def test_component_values_are_html_escaped(self) -> None:
        link = nav_link(
            "custom",
            '/path?value="unsafe"',
            '<script>alert(1)</script>',
            "shield",
            active="none",
        )
        self.assertNotIn('<script>', link)
        self.assertNotIn('"unsafe"', link)
        self.assertIn('&lt;script&gt;', link)
        self.assertIn('&quot;unsafe&quot;', link)

        svg = icon('x" onload="bad')
        self.assertNotIn('onload="bad', svg)
        self.assertIn('&quot;', svg)

    def test_shell_contains_shared_security_and_feedback_components(self) -> None:
        shell = render_console_shell(
            active="overview",
            title="控制台总览",
            content='<section id="content">ok</section>',
            body_marker="test",
        )
        self.assertIn('data-console-ui="test"', shell)
        self.assertIn('id="consoleSidebar"', shell)
        self.assertIn('id="adminTokenDialog"', shell)
        self.assertIn('id="toastRegion"', shell)
        self.assertIn('/control-assets/console.css', shell)
        self.assertIn('/control-assets/console.js', shell)
        self.assertIn('<section id="content">ok</section>', shell)

    def test_token_dialog_is_a_reusable_component(self) -> None:
        dialog = render_admin_token_dialog()
        self.assertIn('<dialog', dialog)
        self.assertIn('WEBUI_ADMIN_TOKEN', dialog)
        self.assertIn('保存并重新读取', dialog)
        self.assertIn('icon-x', dialog)

    def test_overview_page_no_longer_owns_sidebar_or_dialog_markup(self) -> None:
        source = inspect.getsource(pages)
        self.assertNotIn('<aside class="sidebar"', source)
        self.assertNotIn('<dialog class="dialog"', source)
        self.assertIn('render_console_shell', source)


if __name__ == "__main__":
    unittest.main()
