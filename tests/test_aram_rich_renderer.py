import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from renderers.aram_augments_rich_image import (
    ARAM_IMAGE_ASSET_BUDGET_SECONDS,
    ARAM_IMAGE_MAX_BYTES,
    ARAM_IMAGE_MAX_HEIGHT,
    ARAM_IMAGE_WIDTH,
    _collect_asset_urls,
    _compact_build_data,
    _decision_routes,
    build_aram_augment_image_response,
)
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

    def test_compact_build_projection_keeps_equipment_spells_and_skill_order(self):
        payload = {
            "item_builds": [
                {"rank": 1, "items": [{"name": f"核心{i}", "icon": f"https://img/core-{i}.png"} for i in range(6)]},
                {"rank": 2, "items": [{"name": "备选", "icon": "https://img/alt.png"}]},
                {"rank": 3, "items": [{"name": "不展示", "icon": "https://img/hidden.png"}]},
            ],
            "starter_items": [{"items": [{"name": f"出门{i}", "icon": f"https://img/starter-{i}.png"} for i in range(4)]}],
            "boots": [{"items": [{"name": "鞋", "icon": "https://img/boots.png"}]}],
            "summoner_spells": [
                {"name": "闪现", "icon": "https://img/flash.png"},
                {"name": "雪球", "icon": "https://img/snowball.png"},
            ],
            "skill_order": [
                {"key": "Q", "icon": "https://img/q.png"},
                {"key": "E", "icon": "https://img/e.png"},
                {"key": "W", "icon": "https://img/w.png"},
                {"key": "R", "icon": "https://img/r.png"},
            ],
        }

        compact = _compact_build_data(payload)

        self.assertEqual(len(compact["core"]), 2)
        self.assertEqual(len(compact["starter"]), 3)
        self.assertEqual(len(compact["boots"]), 1)
        self.assertEqual([item["name"] for item in compact["spells"]], ["闪现", "雪球"])
        self.assertEqual([item["key"] for item in compact["skills"]], ["Q", "E", "W"])
        urls = _collect_asset_urls("Ezreal", [], compact)
        self.assertIn("https://img/core-0.png", urls)
        self.assertIn("https://img/flash.png", urls)
        self.assertIn("https://img/q.png", urls)
        self.assertNotIn("https://img/hidden.png", urls)
        self.assertNotIn("https://img/r.png", urls)

    def test_compact_renderer_caps_dimensions_bytes_and_asset_wait(self):
        rows = []
        for index, rarity in enumerate([4, 4, 4, 4, 3, 3, 3, 2, 2, 2], start=1):
            rows.append(
                {
                    "rank": index,
                    "name": f"强化{index}",
                    "icon": f"https://img/augment-{index}.png",
                    "rarity": rarity,
                    "performance": 0.50 + index / 100,
                    "popular": 0.20 + index / 100,
                    "games": 1000 + index,
                    "desc": "用于验证紧凑布局仍保留强化说明、胜率、热度和样本信息。",
                }
            )
        payload = {
            "hero": {"alias": "Ezreal", "title": "探险家", "name": "伊泽瑞尔"},
            "rows": rows,
            "total": 191,
            "source": "opgg",
            "updated_at": "2026-08-24 16:38:31",
            "cache_expires_in": 1800,
            "item_builds": [
                {"rank": 1, "items": [{"name": f"核心{i}", "icon": f"https://img/core-{i}.png"} for i in range(5)]},
                {"rank": 2, "items": [{"name": f"备选{i}", "icon": f"https://img/alt-{i}.png"} for i in range(5)]},
            ],
            "starter_items": [{"items": [{"name": f"出门{i}", "icon": f"https://img/starter-{i}.png"} for i in range(3)]}],
            "boots": [{"items": [{"name": "鞋", "icon": "https://img/boots.png"}]}],
            "summoner_spells": [
                {"name": "闪现", "icon": "https://img/flash.png"},
                {"name": "雪球", "icon": "https://img/snowball.png"},
            ],
            "skill_order": [
                {"key": "Q", "icon": "https://img/q.png"},
                {"key": "E", "icon": "https://img/e.png"},
                {"key": "W", "icon": "https://img/w.png"},
            ],
            "timing": {"build_status": "ok"},
        }
        ctx = SimpleNamespace(image_asset_cache=None, aram_augment_cache=None)

        with patch(
            "renderers.aram_augments_rich_image.prefetch_image_urls",
            return_value={},
        ) as prefetch:
            response = build_aram_augment_image_response(ctx, payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/png")
        self.assertLessEqual(len(response.body), ARAM_IMAGE_MAX_BYTES)
        rendered = Image.open(io.BytesIO(response.body))
        self.assertLessEqual(rendered.width, ARAM_IMAGE_WIDTH)
        self.assertLessEqual(rendered.height, ARAM_IMAGE_MAX_HEIGHT)
        self.assertLess(rendered.height, 1100)
        kwargs = prefetch.call_args.kwargs
        self.assertEqual(kwargs["max_workers"], 12)
        self.assertEqual(kwargs["overall_timeout"], ARAM_IMAGE_ASSET_BUDGET_SECONDS)
        self.assertLessEqual(kwargs["timeout"], 1.0)

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
