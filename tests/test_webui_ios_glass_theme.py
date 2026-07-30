import unittest

from lanzou_update_push_api_server.ui_theme import (
    THEME_STORAGE_KEY,
    apply_ios_glass_theme,
)


class WebUiIosGlassThemeTests(unittest.TestCase):
    def test_theme_injection_contains_three_modes_and_persistence(self):
        html = apply_ios_glass_theme("<html><head></head><body><div class='actions'></div></body></html>")
        self.assertIn('id="ios-glass-theme-style"', html)
        self.assertIn('id="ios-glass-theme-bootstrap"', html)
        self.assertIn('id="ios-glass-theme-controller"', html)
        self.assertIn(THEME_STORAGE_KEY, html)
        self.assertIn("['light','☀ 日间']", html)
        self.assertIn("['system','◐ 跟随']", html)
        self.assertIn("['dark','☾ 夜间']", html)
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn("backdrop-filter", html)
        self.assertIn("prefers-reduced-motion", html)

    def test_theme_injection_is_idempotent(self):
        source = "<html><head></head><body></body></html>"
        once = apply_ios_glass_theme(source)
        twice = apply_ios_glass_theme(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count('id="ios-glass-theme-style"'), 1)

    def test_invalid_html_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_ios_glass_theme("<div>missing document shell</div>")


if __name__ == "__main__":
    unittest.main()
