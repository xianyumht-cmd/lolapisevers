import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.responses import Response

from cache import TTLCache
from routers.aram_augments import _build_cached_image_response


class AramAugmentsImageCacheTests(unittest.TestCase):
    def setUp(self):
        locks = {}
        lock_guard = threading.Lock()

        def image_lock(key):
            with lock_guard:
                return locks.setdefault(key, threading.Lock())

        self.ctx = SimpleNamespace(
            aram_image_cache=TTLCache(ttl_seconds=300, max_size=8),
            aram_image_cache_seconds=300,
            aram_image_lock=image_lock,
        )
        self.payload = {
            "hero": {"alias": "Ahri", "name": "阿狸"},
            "rows": [{"name": "强化一", "performance": 0.52}],
            "total": 1,
        }

    def test_rendered_png_is_cached_and_reused(self):
        with patch(
            "routers.aram_augments.build_aram_augment_image_response",
            return_value=Response(content=b"png-bytes", media_type="image/png"),
        ) as renderer:
            first = _build_cached_image_response(self.ctx, self.payload)
            second = _build_cached_image_response(self.ctx, self.payload)

        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(first.headers["x-image-cache"], "miss")
        self.assertEqual(second.headers["x-image-cache"], "hit")
        self.assertEqual(first.body, second.body)
        self.assertEqual(first.headers["etag"], second.headers["etag"])
        self.assertEqual(first.headers["cache-control"], "public, max-age=300")

    def test_matching_etag_returns_not_modified_without_rendering(self):
        with patch(
            "routers.aram_augments.build_aram_augment_image_response",
            return_value=Response(content=b"png-bytes", media_type="image/png"),
        ) as renderer:
            first = _build_cached_image_response(self.ctx, self.payload)
            second = _build_cached_image_response(self.ctx, self.payload, first.headers["etag"])

        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.headers["x-image-cache"], "not-modified")

    def test_payload_change_invalidates_rendered_image(self):
        changed = {**self.payload, "rows": [{"name": "强化二", "performance": 0.61}]}
        with patch(
            "routers.aram_augments.build_aram_augment_image_response",
            return_value=Response(content=b"png-bytes", media_type="image/png"),
        ) as renderer:
            first = _build_cached_image_response(self.ctx, self.payload)
            second = _build_cached_image_response(self.ctx, changed)

        self.assertEqual(renderer.call_count, 2)
        self.assertNotEqual(first.headers["etag"], second.headers["etag"])


if __name__ == "__main__":
    unittest.main()
