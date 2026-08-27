import io
import random
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from renderers.image_utils import (
    NEGATIVE_IMAGE_CACHE_VALUE,
    download_image_cached,
    encode_png_limited,
    image_footer_left,
    image_footer_right,
    prefetch_image_urls,
)


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class ImageUtilsTests(unittest.TestCase):
    def test_footer_branding_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(image_footer_left(), "GroupGuardKing-GGK")
            self.assertEqual(image_footer_right(), "致力于企业级群管解决方案")

    def test_footer_branding_can_be_overridden(self):
        with patch.dict(
            "os.environ",
            {"IMAGE_FOOTER_LEFT": "左侧", "IMAGE_FOOTER_RIGHT": "右侧"},
            clear=True,
        ):
            self.assertEqual(image_footer_left(), "左侧")
            self.assertEqual(image_footer_right(), "右侧")

    def test_download_failure_is_negative_cached(self):
        cache = FakeCache()
        url = "https://assets.invalid/item/1.png"
        with patch("requests.get", side_effect=TimeoutError("offline")):
            self.assertIsNone(download_image_cached(cache, url, timeout=0.01))
        self.assertEqual(cache.get(f"image_asset:{url}"), NEGATIVE_IMAGE_CACHE_VALUE)

    def test_negative_cached_asset_is_not_retried_in_blocking_mode(self):
        cache = FakeCache()
        url = "https://assets.invalid/item/2.png"
        cache.set(f"image_asset:{url}", NEGATIVE_IMAGE_CACHE_VALUE)
        with patch("renderers.image_utils.download_image_cached") as downloader:
            self.assertEqual(
                prefetch_image_urls(cache, [url], blocking_network=True),
                {},
            )
        downloader.assert_not_called()

    def test_default_prefetch_schedules_missing_assets_without_network_wait(self):
        cache = FakeCache()
        urls = [f"https://assets.invalid/item/{index}.png" for index in range(4)]

        started = time.perf_counter()
        with patch("renderers.image_utils._schedule_image_refresh", return_value=True) as scheduler:
            with patch("renderers.image_utils.download_image_cached") as downloader:
                result = prefetch_image_urls(cache, urls)
        elapsed = time.perf_counter() - started

        self.assertEqual(result, {})
        self.assertLess(elapsed, 0.1)
        self.assertEqual(scheduler.call_count, len(urls))
        downloader.assert_not_called()

    def test_prefetch_returns_when_explicit_blocking_budget_expires(self):
        cache = FakeCache()
        urls = [f"https://assets.invalid/item/{index}.png" for index in range(4)]

        def slow_download(_cache, _url, _timeout):
            time.sleep(0.2)
            return b"image"

        started = time.perf_counter()
        with patch("renderers.image_utils.download_image_cached", side_effect=slow_download):
            result = prefetch_image_urls(
                cache,
                urls,
                max_workers=1,
                overall_timeout=0.03,
                blocking_network=True,
            )
        elapsed = time.perf_counter() - started

        self.assertEqual(result, {})
        self.assertLess(elapsed, 0.15)
        for url in urls:
            self.assertEqual(cache.get(f"image_asset:{url}"), NEGATIVE_IMAGE_CACHE_VALUE)

    def test_background_download_failure_does_not_poison_long_negative_cache(self):
        cache = FakeCache()
        url = "https://assets.invalid/item/9.png"
        with patch("requests.get", side_effect=TimeoutError("offline")):
            self.assertIsNone(
                download_image_cached(
                    cache,
                    url,
                    timeout=0.01,
                    negative_cache=False,
                )
            )
        self.assertIsNone(cache.get(f"image_asset:{url}"))

    def test_encode_png_limited_caps_dimensions_and_bytes(self):
        image = Image.new("RGB", (1500, 2400), (18, 24, 39))
        draw = ImageDraw.Draw(image)
        for y in range(0, image.height, 12):
            draw.line((0, y, image.width, y), fill=(y % 255, 120, 180), width=2)

        encoded = encode_png_limited(
            image,
            max_bytes=180_000,
            max_width=1080,
            max_height=1800,
        )

        self.assertLessEqual(len(encoded), 180_000)
        rendered = Image.open(io.BytesIO(encoded))
        self.assertLessEqual(rendered.width, 1080)
        self.assertLessEqual(rendered.height, 1800)

    def test_encode_png_limited_enforces_byte_ceiling_for_noisy_input(self):
        random_bytes = random.Random(7).randbytes(800 * 1200 * 3)
        image = Image.frombytes("RGB", (800, 1200), random_bytes)

        encoded = encode_png_limited(image, max_bytes=150_000)

        self.assertLessEqual(len(encoded), 150_000)
        rendered = Image.open(io.BytesIO(encoded))
        self.assertGreaterEqual(rendered.width, 360)
        self.assertGreaterEqual(rendered.height, 420)


if __name__ == "__main__":
    unittest.main()
