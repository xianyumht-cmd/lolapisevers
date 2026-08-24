import json
import unittest

from renderers.aram_augments_rich_image import _decision_routes
from services.opgg_parser import extract_opgg_augments


class AramRichRendererTests(unittest.TestCase):
    def test_decision_routes_are_distinct_and_keep_single_augment_semantics(self):
        rows = [
            {"name": "稳健", "performance": 0.65, "popular": 0.70},
            {"name": "高胜", "performance": 0.70, "popular": 0.20},
            {"name": "热门", "performance": 0.52, "popular": 0.90},
        ]
        routes = _decision_routes(rows)
        self.assertEqual(len(routes), 3)
        self.assertEqual(len({route[1] for route in routes}), 3)
        self.assertEqual(routes[0][1], "稳健")
        self.assertEqual(routes[1][1], "高胜")
        self.assertEqual(routes[2][1], "热门")

    def test_opgg_augment_parser_preserves_rank_id_sample_and_clean_description(self):
        item = {
            "id": 123,
            "name": "测试强化",
            "largeIcon": "https://example.invalid/augment.png",
            "rarity": 4,
            "performance": 0.6123,
            "popular": 0.4567,
            "gameCount": 9876,
            "desc": "<b>造成 &amp; 提升</b>",
        }
        decoded = "prefix " + json.dumps({"data": [item]}, ensure_ascii=False, separators=(",", ":"))
        escaped = json.dumps(decoded, ensure_ascii=False)[1:-1]
        page = f'<script>self.__next_f.push([1,"{escaped}"])</script>'

        rows = extract_opgg_augments(page)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 123)
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["games"], 9876)
        self.assertEqual(rows[0]["desc"], "造成 & 提升")
        self.assertEqual(rows[0]["performance"], 0.6123)
        self.assertEqual(rows[0]["popular"], 0.4567)


if __name__ == "__main__":
    unittest.main()
