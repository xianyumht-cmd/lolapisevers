import heapq
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple


@dataclass(frozen=True)
class _CacheEntry:
    value: Any
    expires_at: float
    sequence: int


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1024) -> None:
        """初始化TTL缓存。"""
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero")
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._data: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._expiry_heap: List[Tuple[float, int, str]] = []
        self._sequence = 0
        self._lock = threading.Lock()

    def _purge_expired_locked(self, now: float) -> None:
        """Remove all expired entries, including keys that are never read again."""
        while self._expiry_heap and self._expiry_heap[0][0] <= now:
            _expires_at, sequence, key = heapq.heappop(self._expiry_heap)
            item = self._data.get(key)
            if item is not None and item.sequence == sequence:
                self._data.pop(key, None)

    def _compact_expiry_heap_locked(self) -> None:
        # Capacity eviction and overwrites leave stale heap records behind. Keep
        # those bookkeeping records bounded as well as the actual cache entries.
        threshold = max(self.max_size * 2, len(self._data) * 2 + 64)
        if len(self._expiry_heap) <= threshold:
            return
        self._expiry_heap = [
            (item.expires_at, item.sequence, key)
            for key, item in self._data.items()
        ]
        heapq.heapify(self._expiry_heap)

    def set(self, key: str, value: Any) -> None:
        """写入缓存项。"""
        with self._lock:
            now = time.monotonic()
            self._purge_expired_locked(now)
            self._sequence += 1
            item = _CacheEntry(
                value=value,
                expires_at=now + self.ttl_seconds,
                sequence=self._sequence,
            )
            self._data.pop(key, None)
            self._data[key] = item
            heapq.heappush(self._expiry_heap, (item.expires_at, item.sequence, key))
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)
            self._compact_expiry_heap_locked()

    def get(self, key: str) -> Optional[Any]:
        """读取缓存项，过期则自动删除。"""
        with self._lock:
            self._purge_expired_locked(time.monotonic())
            item = self._data.get(key)
            if item is None:
                return None
            self._data.move_to_end(key)
            return item.value

    def get_with_remaining_ttl(self, key: str) -> Tuple[Optional[Any], int]:
        """读取缓存项并返回剩余TTL秒数。"""
        with self._lock:
            now = time.monotonic()
            self._purge_expired_locked(now)
            item = self._data.get(key)
            if item is None:
                return None, 0
            self._data.move_to_end(key)
            remain = max(int(item.expires_at - now), 0)
            return item.value, remain

    def contains(self, key: str) -> bool:
        """判断缓存键是否有效。"""
        return self.get(key) is not None

    def __len__(self) -> int:
        """Return the number of live entries."""
        with self._lock:
            self._purge_expired_locked(time.monotonic())
            return len(self._data)
