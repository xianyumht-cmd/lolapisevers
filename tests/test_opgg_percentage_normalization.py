import unittest

from services.opgg_parser import normalize_opgg_ratio
from utils.formatters import pct


class OpggPercentageNormalizationTests(unittest.TestCase):
    def test_decimal_ratio_is_preserved(self):
        self.assertAlmostEqual(normalize_opgg_ratio(0.918), 0.918)
        self.assertEqual(pct(normalize_opgg_ratio(0.918)), "91.8%")

    def test_percentage_point_value_is_scaled_once(self):
        self.assertAlmostEqual(normalize_opgg_ratio(91.8), 0.918)
        self.assertAlmostEqual(normalize_opgg_ratio(6.84), 0.0684)
        self.assertEqual(pct(normalize_opgg_ratio(91.8)), "91.8%")
        self.assertEqual(pct(normalize_opgg_ratio(6.84)), "6.84%")

    def test_explicit_percent_string_is_supported(self):
        self.assertAlmostEqual(normalize_opgg_ratio("91.8%"), 0.918)
        self.assertAlmostEqual(normalize_opgg_ratio("0.5%"), 0.005)

    def test_invalid_metrics_are_rejected_instead_of_rendered_over_100_percent(self):
        for value in [None, "", "abc", -1, 100.01, float("inf"), float("nan"), True]:
            self.assertIsNone(normalize_opgg_ratio(value), msg=repr(value))

    def test_boundaries_remain_valid_ratios(self):
        self.assertEqual(normalize_opgg_ratio(0), 0.0)
        self.assertEqual(normalize_opgg_ratio(1), 1.0)
        self.assertEqual(normalize_opgg_ratio(100), 1.0)


if __name__ == "__main__":
    unittest.main()
