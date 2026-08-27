import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cache import TTLCache
from renderers import cross_image


class CrossImageCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache_patcher = patch.object(
            cross_image,
            "_BATTLE_IMAGE_CACHE",
            TTLCache(ttl_seconds=120, max_size=8),
        )
        self.cache_patcher.start()
        self.addCleanup(self.cache_patcher.stop)
        self.ctx = SimpleNamespace(image_asset_cache=None, aram_augment_cache=None)

    def _payload(self, *, name="缓存测试", wins=3):
        return {
            "name": name,
            "region": "艾欧尼亚",
            "level": 100,
            "rank": "黄金 I",
            "last_online_time": "刚刚",
            "winrate_recent": "60%",
            "avg_kda_recent": 3.2,
            "is_stale": False,
            "profile_icon": 0,
            "ranked_queues": [
                {"queue_name": "单双排", "rank": "黄金 I", "wins": wins, "losses": 2}
            ],
            "recent_matches": [],
        }

    def test_identical_visible_payload_reuses_rendered_png(self):
        payload = self._payload()
        with patch("renderers.cross_image.prefetch_image_urls", return_value={}):
            with patch("renderers.cross_image.encode_png_limited", return_value=b"first-png") as encoder:
                first = cross_image.build_cross_image_response(self.ctx, payload)

            with patch(
                "renderers.cross_image.encode_png_limited",
                side_effect=AssertionError("cache hit should not re-encode"),
            ):
                second = cross_image.build_cross_image_response(self.ctx, dict(payload))

        self.assertEqual(first.body, b"first-png")
        self.assertEqual(second.body, b"first-png")
        self.assertEqual(first.headers.get("x-image-cache"), "miss")
        self.assertEqual(second.headers.get("x-image-cache"), "hit")
        encoder.assert_called_once()

    def test_changed_business_payload_misses_final_image_cache(self):
        first_payload = self._payload(wins=3)
        changed_payload = self._payload(wins=4)
        with patch("renderers.cross_image.prefetch_image_urls", return_value={}):
            with patch(
                "renderers.cross_image.encode_png_limited",
                side_effect=[b"first-png", b"new-png"],
            ) as encoder:
                first = cross_image.build_cross_image_response(self.ctx, first_payload)
                second = cross_image.build_cross_image_response(self.ctx, changed_payload)

        self.assertEqual(first.body, b"first-png")
        self.assertEqual(second.body, b"new-png")
        self.assertEqual(encoder.call_count, 2)
        self.assertEqual(second.headers.get("x-image-cache"), "miss")


if __name__ == "__main__":
    unittest.main()
