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


def _bounded_int(name: str, default: int, minimum: int, maximum: int, errors: list[str]) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        errors.append(f"{name} 必须是整数，当前值为 {raw!r}")
        return default
    if value < minimum or value > maximum:
        errors.append(f"{name} 必须在 {minimum}-{maximum} 之间，当前值为 {value}")
        return default
    return value


def _strict_bool(name: str, default: bool, errors: list[str]) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    errors.append(f"{name} 必须是 true/false 或 1/0，当前值为 {raw!r}")
    return default


def load_config() -> AppConfig:
    errors: list[str] = []
    app_port = _bounded_int("APP_PORT", 5001, 1, 65535, errors)
    cache_seconds = _bounded_int("CACHE_SECONDS", 300, 1, 86400, errors)
    shard_cache_seconds = _bounded_int("SHARD_CACHE_SECONDS", 600, 1, 86400, errors)
    aram_cache_seconds = _bounded_int("ARAM_AUGMENT_CACHE_SECONDS", 1800, 1, 86400, errors)
    mysql_port = _bounded_int("MYSQL_PORT", 3306, 1, 65535, errors)
    so1_timeout_ms = _bounded_int("SO1_TIMEOUT_MS", 20000, 1000, 300000, errors)
    so1_headless = _strict_bool("SO1_HEADLESS", True, errors)
    if errors:
        raise ValueError("配置错误：" + "；".join(errors))
    return AppConfig(
        app_host=os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
        app_port=app_port,
        cache_seconds=cache_seconds,
        shard_cache_seconds=shard_cache_seconds,
        aram_augment_cache_seconds=aram_cache_seconds,
        shard_data_url=os.getenv(
            "SHARD_DATA_URL",
            "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json",
        ),
        shard_hero_url=os.getenv(
            "SHARD_HERO_URL",
            "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js",
        ),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1").strip() or "127.0.0.1",
        mysql_port=mysql_port,
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_database=os.getenv("MYSQL_DATABASE", "lol_data"),
        so1_username=os.getenv("SO1_USERNAME", "").strip(),
        so1_password=os.getenv("SO1_PASSWORD", "").strip(),
        so1_headless=so1_headless,
        so1_timeout_ms=so1_timeout_ms,
    )
