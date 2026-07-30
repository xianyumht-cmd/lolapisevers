import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.image_asset_store import (
    DiskImageAssetStore,
    PersistentImageAssetCache,
    classify_image_url,
    image_asset_url,
)


def png_bytes(color=(20, 40, 60)) -> bytes:
    image = Image.new("RGB", (16, 16), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ImageAssetStoreTests(unittest.TestCase):
    def test_known_urls_use_stable_kind_and_numeric_id(self):
        self.assertEqual(
            classify_image_url(image_asset_url("profile", 6522)),
            ("profile", "6522"),
        )
        self.assertEqual(
            classify_image_url(image_asset_url("champion", 236)),
            ("champion", "236"),
        )
        self.assertEqual(
            classify_image_url(image_asset_url("item", 6696)),
            ("item", "6696"),
        )

    def test_write_and_read_use_stable_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DiskImageAssetStore(Path(temp), ttl_days=0)
            url = image_asset_url("champion", 236)
            result = store.write_url(url, png_bytes())

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "downloaded")
            self.assertTrue((Path(temp) / "champion" / "236.png").is_file())
            self.assertEqual(store.read_url(url), png_bytes())

    def test_zero_ttl_means_permanent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DiskImageAssetStore(Path(temp), ttl_days=0)
            url = image_asset_url("item", 6696)
            store.write_url(url, png_bytes())
            path = store.path_for_url(url)
            old = time.time() - 3650 * 86400
            os.utime(path, (old, old))

            self.assertIsNotNone(store.read_url(url))
            self.assertEqual(store.status()["expired_files"], 0)

    def test_expired_file_is_stale_but_preserved_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DiskImageAssetStore(Path(temp), ttl_days=1)
            url = image_asset_url("profile", 6522)
            original = png_bytes((10, 20, 30))
            store.write_url(url, original)
            path = store.path_for_url(url)
            old = time.time() - 2 * 86400
            os.utime(path, (old, old))

            self.assertIsNone(store.read_url(url))
            with patch("requests.get", side_effect=TimeoutError("offline")):
                result = store.fetch_url(url, force=True, timeout=0.01)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "stale")
            self.assertEqual(path.read_bytes(), original)

    def test_manual_disk_update_wins_over_old_memory_value(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DiskImageAssetStore(Path(temp), ttl_days=0)
            cache = PersistentImageAssetCache(
                ttl_seconds=3600,
                max_size=8,
                store=store,
            )
            url = image_asset_url("champion", 236)
            key = f"image_asset:{url}"
            old = png_bytes((1, 2, 3))
            new = png_bytes((4, 5, 6))
            cache.memory.set(key, old)
            store.write_url(url, new)

            self.assertEqual(cache.get(key), new)

    def test_status_reports_counts_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DiskImageAssetStore(Path(temp), ttl_days=0)
            store.write_url(image_asset_url("champion", 1), png_bytes())
            store.write_url(image_asset_url("item", 2), png_bytes())
            store.write_url(image_asset_url("profile", 3), png_bytes())
            status = store.status()

            self.assertEqual(status["counts"]["champion"], 1)
            self.assertEqual(status["counts"]["item"], 1)
            self.assertEqual(status["counts"]["profile"], 1)
            self.assertEqual(status["total_files"], 3)
            self.assertGreater(status["total_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
