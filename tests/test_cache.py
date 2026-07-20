import unittest
from unittest.mock import patch

from cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_expired_entries_are_purged_without_reading_the_same_key(self) -> None:
        cache = TTLCache(ttl_seconds=10, max_size=4)

        with patch("cache.time.monotonic", return_value=100.0):
            cache.set("expired", "old")
        with patch("cache.time.monotonic", return_value=111.0):
            cache.set("fresh", "new")
            self.assertNotIn("expired", cache._data)
            self.assertEqual(cache.get("fresh"), "new")

    def test_capacity_limit_evicts_least_recently_used_entry(self) -> None:
        cache = TTLCache(ttl_seconds=60, max_size=2)
        cache.set("first", 1)
        cache.set("second", 2)

        self.assertEqual(cache.get("first"), 1)
        cache.set("third", 3)

        self.assertIsNone(cache.get("second"))
        self.assertEqual(cache.get("first"), 1)
        self.assertEqual(cache.get("third"), 3)
        self.assertEqual(len(cache), 2)

    def test_max_size_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            TTLCache(max_size=0)


if __name__ == "__main__":
    unittest.main()
