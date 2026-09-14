from __future__ import annotations

import inspect
import unittest

from lanzou_update_push_api_server import lolban_console
from lanzou_update_push_api_server.control_ui import ASSET_DIRECTORY, render_lolban_console_page


class LolbanConsoleUiBoundaryTests(unittest.TestCase):
    def test_backend_reexports_control_ui_renderer(self) -> None:
        self.assertIs(lolban_console.render_lolban_console_page, render_lolban_console_page)

    def test_backend_no_longer_embeds_page_css_or_javascript(self) -> None:
        source = inspect.getsource(lolban_console)

        self.assertNotIn("<style>", source)
        self.assertNotIn("const S=", source)
        self.assertNotIn("function providerSecretControl", source)
        self.assertIn("install_lolban_console_routes", source)

    def test_renderer_uses_owned_assets(self) -> None:
        page = render_lolban_console_page()

        self.assertIn('/control-assets/lolban.css', page)
        self.assertIn('/control-assets/lolban.js', page)
        self.assertTrue((ASSET_DIRECTORY / "lolban.css").is_file())
        self.assertTrue((ASSET_DIRECTORY / "lolban.js").is_file())


if __name__ == "__main__":
    unittest.main()
