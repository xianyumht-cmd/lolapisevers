# lolapisevers

`lolapisevers` 是一个在 Windows 本地运行的英雄联盟数据 API 服务，基于 `FastAPI + MySQL + Playwright`。当前主要提供 so1 跨区查询、英雄碎片、极地大乱斗强化符文和 LOL 封禁查询，并可在实时抓取失败时使用 MySQL 快照回退。

仓库还包含一个独立的蓝奏云更新监控服务，默认运行在 `6178` 端口。详细配置见 `lanzou_update_push_api_server/README.md`。

## 环境要求

- Python 3.10+
- Windows
- MySQL 8+
- Playwright Chromium

## 安装

在项目目录打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD "ms-playwright"
.\.venv\Scripts\python.exe -m playwright install chromium
```

使用虚拟环境里的 Python 安装 Chromium，可避免浏览器被装到错误的 Python 环境。

## 本机配置

先复制安全模板：

```powershell
Copy-Item .\ops\app_env.example.ps1 .\ops\app_env.local.ps1
```

然后只在本机编辑 `ops/app_env.local.ps1`。该文件已被 Git 忽略，不要把真实密码、token、cookie 或登录状态提交到仓库。

关键配置示例：

```powershell
# MySQL
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "CHANGE_ME"
$env:MYSQL_PASSWORD = "CHANGE_ME"
$env:MYSQL_DATABASE = "lol_data"

# so1
$env:SO1_USERNAME = "CHANGE_ME"
$env:SO1_PASSWORD = "CHANGE_ME"
$env:SO1_HEADLESS = "1"
$env:SO1_TIMEOUT_MS = "20000"
$env:SO1_MAX_CONCURRENT_PAGES = "2"

# API
$env:APP_HOST = "0.0.0.0"
$env:APP_PORT = "5001"
```

## 启动服务

推荐使用统一启动入口，它会先加载 `ops/app_env.local.ps1`，再启动主 API 和蓝奏云监控：

```powershell
.\run_server.bat
```

也可以直接运行服务脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\run_service.ps1
```

需要隐藏窗口时可双击 `start_hidden.vbs`。正式长期运行建议使用项目已有的 `LOLDataSystem` Windows 服务配置。

直接执行 `python app.py` 不会自动加载 `ops/app_env.local.ps1`；只有在当前终端已经手动设置好全部环境变量时才应这样启动。

## 健康检查

```powershell
Invoke-RestMethod "http://127.0.0.1:5001/health"
```

完全就绪时返回：

```json
{
  "status": "ok",
  "liveness": "up",
  "ready": true,
  "mysql": "up",
  "mysql_error": "",
  "so1_browser": "up",
  "so1_max_concurrent_pages": 2
}
```

健康端始终用 HTTP 200 表示 API 进程仍能响应，并通过字段区分状态：

- `liveness=up`：API 进程存活，健康端可访问。
- `ready=true` 且 `status=ok`：MySQL 与 so1 浏览器均可用，可以接管业务流量。
- `ready=false` 且 `status=degraded`：进程仍存活，但至少一个必要依赖不可用，不应判定为接管成功。

完整只读诊断：

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\health_check.ps1
```

## 当前接口

### 跨区查询

```http
GET /cross_query?name={召唤师名}&region={大区}&output=pretty|raw|image|svg
```

示例：

```powershell
Invoke-RestMethod "http://127.0.0.1:5001/cross_query?name=testplayer%2312345&region=HN1&output=pretty"
```

### 人工初始化 so1 会话

```http
POST /cross_session_init?wait_seconds=180
```

当 so1 出现验证码或自动登录失效时使用。接口会打开可视浏览器，等待人工完成登录和验证，并保存会话。

### 英雄碎片查询

```http
GET /shard_query?hero={英雄名}&output=image|json
```

### 极地大乱斗强化查询

```http
GET /aram_augments?hero={英雄名}&output=image|json
```

### LOL 封禁查询

```http
GET /lolban?qq={QQ号}&output=text|json
GET /api/v2/lolban?qq={QQ号}&output=text|json
```

FastAPI 自动接口文档：

- `http://127.0.0.1:5001/docs`
- `http://127.0.0.1:5001/redoc`

## 常见问题

### 健康端无法访问

依次检查服务、端口和日志：

```powershell
Get-Service LOLDataSystem
Get-NetTCPConnection -LocalPort 5001 -State Listen
Get-Content .\logs\service.stderr.log -Tail 80
```

不要同时通过 `run_server.bat`、`start_hidden.vbs` 和 Windows 服务启动多套 `app.py`，否则会出现端口占用。

### `mysql=down`

- 确认 MySQL 服务已经启动。
- 检查 `ops/app_env.local.ps1` 中的主机、端口、账号、密码和库名。
- 确认 `3306` 端口可达。

### `so1_browser=down`

- 重启服务并查看 `logs/service.stderr.log`。
- 确认 Playwright Chromium 安装到了 `PLAYWRIGHT_BROWSERS_PATH` 指向的位置。
- 必要时重新运行：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD "ms-playwright"
.\.venv\Scripts\python.exe -m playwright install chromium
```

### `cross_query` 返回 `source=snapshot`

这表示实时抓取失败，系统回退到了 MySQL 中最近一次成功快照。先查看返回中的 `fallback_reason` 和服务日志；若是验证码问题，再调用 `/cross_session_init`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
