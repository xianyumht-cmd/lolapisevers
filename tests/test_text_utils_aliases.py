import unittest

from utils.text_utils import normalize_search_text


class TextUtilsAliasTests(unittest.TestCase):
    def test_kalista_common_chinese_nickname_is_canonicalized(self):
        self.assertEqual(normalize_search_text("滑板鞋"), "kalista")

    def test_regular_search_text_is_unchanged_except_normalization(self):
        self.assertEqual(normalize_search_text("  Ka Li Sta  "), "kalista")


if __name__ == "__main__":
    unittest.main()
