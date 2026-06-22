import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    app_host: str
    app_port: int
    cache_seconds: int
    shard_cache_seconds: int
    aram_augment_cache_seconds: int
    shard_data_url: str
    shard_hero_url: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    so1_username: str
    so1_password: str
    so1_headless: bool
    so1_timeout_ms: int

    @property
    def db_config(self) -> dict:
        return {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "database": self.mysql_database,
        }


def load_config() -> AppConfig:
    return AppConfig(
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "5001")),
        cache_seconds=int(os.getenv("CACHE_SECONDS", "300")),
        shard_cache_seconds=int(os.getenv("SHARD_CACHE_SECONDS", "600")),
        aram_augment_cache_seconds=int(os.getenv("ARAM_AUGMENT_CACHE_SECONDS", "1800")),
        shard_data_url=os.getenv(
            "SHARD_DATA_URL",
            "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json",
        ),
        shard_hero_url=os.getenv(
            "SHARD_HERO_URL",
            "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js",
        ),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", "123456"),
        mysql_database=os.getenv("MYSQL_DATABASE", "lol_data"),
        so1_username=os.getenv("SO1_USERNAME", "mengxin1").strip(),
        so1_password=os.getenv("SO1_PASSWORD", "mengxin").strip(),
        so1_headless=os.getenv("SO1_HEADLESS", "1") != "0",
        so1_timeout_ms=int(os.getenv("SO1_TIMEOUT_MS", "20000")),
    )
