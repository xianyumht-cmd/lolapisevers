# lolapisevers environment template
# Copy this file to ops\app_env.local.ps1 on the target machine and fill in real values there.
# Do not commit real passwords, tokens, cookies, or account credentials.

# App
$env:APP_HOST = "0.0.0.0"
$env:APP_PORT = "5001"
$env:PYTHONIOENCODING = "utf-8"
$env:REQUIRE_BUILD_INFO = "1"

# WebUI security
# Leave empty for loopback-only administration. Set a strong random token before allowing LAN access.
$env:WEBUI_ADMIN_TOKEN = ""

# Cache
$env:CACHE_SECONDS = "300"
$env:SHARD_CACHE_SECONDS = "600"
$env:ARAM_AUGMENT_CACHE_SECONDS = "1800"

# Image rendering
# Footer branding can be adjusted locally without modifying source code.
$env:IMAGE_FOOTER_LEFT = "GroupGuardKing-GGK"
$env:IMAGE_FOOTER_RIGHT = "致力于企业级群管解决方案"
$env:IMAGE_MAX_BYTES = "760000"
$env:IMAGE_MAX_WIDTH = "1080"
$env:IMAGE_MAX_HEIGHT = "1800"

# Persistent image assets
# 0 days means permanent storage. Known assets use stable filenames such as champion\236.png.
$env:IMAGE_ASSET_DISK_CACHE_ENABLED = "1"
$env:IMAGE_ASSET_CACHE_DIR = "data\image-cache"
$env:IMAGE_ASSET_CACHE_TTL_DAYS = "0"
$env:IMAGE_ASSET_SYNC_WORKERS = "8"
$env:IMAGE_ASSET_SYNC_TIMEOUT_SECONDS = "8"

# Data sources
$env:SHARD_DATA_URL = "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json"
$env:SHARD_HERO_URL = "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js"

# Persistent upstream snapshots
# Shard and hero catalog snapshots survive service restarts. Seven days is the
# maximum age accepted for those relatively stable source files.
$env:UPSTREAM_SNAPSHOT_DIR = "data\upstream_snapshots"
$env:SHARD_SNAPSHOT_MAX_AGE_SECONDS = "604800"
# Per-hero ARAM result snapshots are more time-sensitive. The default accepts
# only the latest 24 hours when OP.GG is unavailable; older snapshots return 503.
$env:ARAM_SNAPSHOT_MAX_AGE_SECONDS = "86400"

# LOL ban providers
# JSON array order is the fallback order. Put real URLs, tokens, headers, and form
# fields only in ops\app_env.local.ps1; the example intentionally has no live provider.
$env:LOL_BAN_PROVIDERS_JSON = "[]"
$env:LOL_BAN_TIMEOUT = "10"
$env:LOL_BAN_NORMAL_CACHE_SECONDS = "60"
$env:LOL_BAN_BANNED_CACHE_SECONDS = "300"
# Last-known-good results remain usable only within this window. The persistent
# snapshot uses the same bound and is restored after a service restart.
$env:LOL_BAN_STALE_CACHE_SECONDS = "86400"
$env:LOL_BAN_MAX_STALE_ENTRIES = "1024"
$env:LOL_BAN_SNAPSHOT_ENABLED = "1"

# MySQL
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "CHANGE_ME"
$env:MYSQL_DATABASE = "lol_data"

# so1 account
$env:SO1_USERNAME = "CHANGE_ME"
$env:SO1_PASSWORD = "CHANGE_ME"
$env:SO1_HEADLESS = "1"
$env:SO1_TIMEOUT_MS = "20000"
$env:SO1_MAX_CONCURRENT_PAGES = "2"

# Playwright
# Keep Chromium inside the project directory if you want a portable runtime.
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\project2\lolapisevers\ms-playwright"

# Keepalive
$env:KEEPALIVE_BASE_URL = "http://127.0.0.1:5001"
$env:KEEPALIVE_TEST_NAME = "testplayer#12345"
$env:KEEPALIVE_TEST_REGION = "HN1"
