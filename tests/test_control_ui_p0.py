from __future__ import annotations

import unittest

from lanzou_update_push_api_server.control_ui import ASSET_DIRECTORY, render_overview_page


class ControlUiP0Tests(unittest.TestCase):
    def test_overview_uses_new_console_shell(self) -> None:
        html = render_overview_page()
        self.assertIn('data-console-ui="p0"', html)
        self.assertIn('/control-assets/console.css', html)
        self.assertIn('/control-assets/console.js', html)
        self.assertIn('class="sidebar"', html)
        self.assertIn('class="topbar"', html)
        self.assertIn('控制台总览', html)
        self.assertIn('封号 Provider', html)
        self.assertIn('最近配置变更', html)
        self.assertIn('/legacy-ui', html)
        self.assertNotIn('class="glass"', html)
        self.assertNotIn('control-navigation-style', html)

    def test_assets_are_local_and_professional(self) -> None:
        css = (ASSET_DIRECTORY / 'console.css').read_text(encoding='utf-8')
        script = (ASSET_DIRECTORY / 'console.js').read_text(encoding='utf-8')
        icons = (ASSET_DIRECTORY / 'icons.svg').read_text(encoding='utf-8')

        self.assertIn('"Microsoft YaHei UI"', css)
        self.assertIn('"Microsoft YaHei"', css)
        self.assertIn('"Cascadia Mono"', css)
        self.assertNotIn('radial-gradient', css)
        self.assertNotIn('linear-gradient', css)
        self.assertNotIn('backdrop-filter', css)

        for endpoint in (
            '/admin/overview',
            '/admin/query-console/lolban',
            '/admin/audit?limit=10',
            '/admin/logs',
            '/admin/service/status',
            '/build-info',
        ):
            self.assertIn(endpoint, script)
        self.assertNotIn('alert(', script)
        self.assertNotIn('confirm(', script)

        for symbol in (
            'icon-dashboard',
            'icon-shield',
            'icon-workflow',
            'icon-key',
            'icon-server',
            'icon-activity',
        ):
            self.assertIn(symbol, icons)


if __name__ == '__main__':
    unittest.main()
