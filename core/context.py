import logging
import threading
from typing import Optional

from cache import TTLCache
from db import Database
from so1_client import So1Client

from core.config import AppConfig, load_config


class AppContext:
    def __init__(self, config: AppConfig, so1_client: Optional[So1Client] = None):
        self.config = config
        self.logger = logging.getLogger("LOLDataSystem")
        self.db_config = config.db_config
        self.db: Optional[Database] = None
        self._db_lock = threading.Lock()
        self.db_error_message = ""
        self.cross_cache = TTLCache(ttl_seconds=config.cache_seconds)
        self.shard_cache = TTLCache(ttl_seconds=config.shard_cache_seconds)
        self.aram_augment_cache = TTLCache(ttl_seconds=config.aram_augment_cache_seconds)
        self.so1_client = so1_client or So1Client(
            username=config.so1_username,
            password=config.so1_password,
            headless=config.so1_headless,
            timeout_ms=config.so1_timeout_ms,
        )
        self.ensure_db()

    def ensure_db(self) -> Optional[Database]:
        if self.db is not None:
            return self.db
        with self._db_lock:
            if self.db is not None:
                return self.db
            try:
                self.db = Database(**self.db_config)
                self.db_error_message = ""
                return self.db
            except Exception as exc:
                self.db_error_message = str(exc)
                self.logger.error("数据库初始化/重连失败: %s", exc)
                return None


def create_app_context(config: Optional[AppConfig] = None, so1_client: Optional[So1Client] = None) -> AppContext:
    return AppContext(config or load_config(), so1_client=so1_client)
