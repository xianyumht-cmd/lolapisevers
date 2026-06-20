import threading
import time
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        """初始化TTL缓存。"""
        self.ttl_seconds = ttl_seconds
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any) -> None:
        """写入缓存项。"""
        with self._lock:
            self._data[key] = {"value": value, "ts": time.time()}

    def get(self, key: str) -> Optional[Any]:
        """读取缓存项，过期则自动删除。"""
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if time.time() - item["ts"] > self.ttl_seconds:
                self._data.pop(key, None)
                return None
            return item["value"]

    def get_with_remaining_ttl(self, key: str) -> Tuple[Optional[Any], int]:
        """读取缓存项并返回剩余TTL秒数。"""
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None, 0
            elapsed = time.time() - item["ts"]
            if elapsed > self.ttl_seconds:
                self._data.pop(key, None)
                return None, 0
            remain = max(int(self.ttl_seconds - elapsed), 0)
            return item["value"], remain

    def contains(self, key: str) -> bool:
        """判断缓存键是否有效。"""
        return self.get(key) is not None
