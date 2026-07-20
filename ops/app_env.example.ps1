# lolapisevers environment template
# Copy this file to ops\app_env.local.ps1 on the target machine and fill in real values there.
# Do not commit real passwords, tokens, cookies, or account credentials.

# App
$env:APP_HOST = "0.0.0.0"
$env:APP_PORT = "5001"
$env:PYTHONIOENCODING = "utf-8"

# WebUI security
# Leave empty for loopback-only administration. Set a strong random token before allowing LAN access.
$env:WEBUI_ADMIN_TOKEN = ""

# Cache
$env:CACHE_SECONDS = "300"
$env:SHARD_CACHE_SECONDS = "600"
$env:ARAM_AUGMENT_CACHE_SECONDS = "1800"

# Data sources
$env:SHARD_DATA_URL = "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json"
$env:SHARD_HERO_URL = "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js"

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
