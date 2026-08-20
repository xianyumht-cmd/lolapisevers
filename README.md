# lolapisevers

`lolapisevers` 是一个在 Windows 本地长期运行的英雄联盟数据接口与运维控制系统，核心由 **FastAPI + MySQL + Playwright** 组成。

当前仓库不是只有一个 `5001` 查询 API：正式运行结构同时包含 **5001 业务接口** 与 **6178 蓝奏监控 / 管理控制台**。README 以 `master` 当前代码为准，历史部署状态和具体修复记录请结合 `CHANGELOG.md`、`PROJECT_INDEX.md` 与 `SERVICE_RUNBOOK.md` 查看。

## 当前能力

### 5001 业务接口

- so1 跨区查询，实时抓取失败时可回退到 MySQL 最近成功快照；
- 英雄碎片查询；
- 极地大乱斗强化符文与基础 Buff / Debuff 数据查询；
- LOL 封禁查询，多 Provider 编排、缓存和降级；
- JSON、文本、PNG、SVG 等输出形式；
- `health / livez / readyz / build-info` 运行与发布追溯接口。

### 6178 管理与蓝奏监控

- 蓝奏云更新监控、文件变化快照、事件记录与 SnowLuma 通知；
- 专业化控制台 Shell、侧栏导航、管理令牌 Dialog、状态卡与本地 SVG 资源；
- 封号 Provider 独立配置与实时诊断；
- 接口与解析中心、Secret 管理、备份与回滚；
- 日志、诊断、安全与系统管理独立页面；
- 蓝奏全局配置、监控项目、通知目标独立页面；
- 独立接口调试器。

## 当前运行拓扑

正式长期运行只保留 `LOLDataSystem` Windows 服务作为唯一入口：

```text
LOLDataSystem / NSSM
  -> powershell.exe -> ops/run_service.ps1
       -> python app.py                            (5001)
       -> python -m lanzou_update_push_api_server (6178)
```

`ops/run_service.ps1` 会加载本机配置并启动两个进程。不要同时使用 Windows 服务、`run_server.bat`、`start_hidden.vbs` 启动多套实例，否则容易造成 5001 / 6178 端口冲突。

`ops/install_persistence.ps1 -Apply` 会把指向当前项目 `start_hidden.vbs`、`run_server.bat` 或 `ops/run_service.ps1` 的旧 Startup 启动项安全移出启动目录并备份到 `logs/retired-startup/`，避免从旧的“登录自启”方案迁移到 NSSM 后仍留下第二条启动链。

## 环境要求

- Windows
- Python 3.10+
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

## 本机配置

复制安全模板：

```powershell
Copy-Item .\ops\app_env.example.ps1 .\ops\app_env.local.ps1
```

只在本机编辑 `ops/app_env.local.ps1`。该文件已被 Git 忽略，不要把真实密码、Token、Cookie、API Key 或登录态提交到仓库。

常见基础配置：

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

# 主 API
$env:APP_HOST = "0.0.0.0"
$env:APP_PORT = "5001"
```

6178 蓝奏监控自身配置使用：

```text
lanzou_update_push_api_server/config.json
```

安全模板为：

```text
lanzou_update_push_api_server/config.example.json
```

第三方蓝奏解析 API Key 应使用环境变量（例如 `LANZOU_API_KEY`），不要写进仓库。

## 启动

### 正式长期运行

持久化安装或修复时使用管理员 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\install_persistence.ps1 -Apply
```

之后日常只通过 Windows 服务管理：

```powershell
Start-Service LOLDataSystem
Restart-Service LOLDataSystem
Stop-Service LOLDataSystem
```

持久化安装器会检查当前项目的旧 Startup 启动项；命中项不会直接删除，而是移动到 `logs/retired-startup/<时间戳>/` 并写入 `manifest.json`。如果持久化安装失败，脚本会尝试恢复刚移走的旧启动项。

### 手动调试

需要前台/手动调试时可以临时使用：

```powershell
.\run_server.bat
```

或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\run_service.ps1
```

需要隐藏窗口的临时手动运行场景可使用：

```text
start_hidden.vbs
```

**不要**在已经启用 `LOLDataSystem` 自动服务时，再把 `run_server.bat` 或 `start_hidden.vbs` 放进 Windows Startup、Run 注册表或其它开机/登录自启位置。

> 直接执行 `python app.py` 不会自动加载 `ops/app_env.local.ps1`。只有当前终端已经手动设置好全部所需环境变量时才应这样运行。

## 5001 健康与发布追溯

```powershell
Invoke-RestMethod "http://127.0.0.1:5001/health"
Invoke-RestMethod "http://127.0.0.1:5001/livez"
Invoke-RestMethod "http://127.0.0.1:5001/readyz"
Invoke-RestMethod "http://127.0.0.1:5001/build-info"
```

语义：

- `/health`：兼容健康状态，进程可响应时保持 HTTP 可访问；
- `/livez`：只判断 API 进程是否存活；
- `/readyz`：检查 MySQL 与 so1 浏览器等必要依赖，未就绪时返回 503；
- `/build-info`：返回部署源码身份，用于确认生产实例对应哪个 Git 提交。

完整只读体检：

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\health_check.ps1
```

体检会额外输出 `Runtime topology`：确认 `run_service.ps1` 是否只有一个由 `LOLDataSystem` 服务拥有的实例，并检查是否还残留指向当前项目的旧 Startup 启动项。拓扑告警目前单独报告，不改变 HTTP readiness 的退出码。

生成部署追溯元数据：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Generate-BuildInfo.ps1
```

部署包应包含生成的 `build-info.json`，但该运行产物不提交到 Git。生产部署状态应以目标机器的 `/build-info` 和部署验证报告为准，不应只根据仓库里某个历史 Changelog 条目推断。

## 5001 当前主要接口

### 跨区查询

```http
GET /cross_query?name={召唤师名}&region={大区}&output=pretty|raw|image|svg
```

实时抓取失败时可返回 MySQL 快照，并在结果中标明回退原因。

### 人工初始化 so1 会话

```http
POST /cross_session_init?wait_seconds=180
```

so1 出现验证码或自动登录失效时使用，可打开可视浏览器等待人工完成登录与验证并保存会话。

### 英雄碎片

```http
GET /shard_query?hero={英雄名}&output=image|json
```

### 极地大乱斗强化 / 基础平衡数据

```http
GET /aram_augments?hero={英雄名}&output=image|json
```

当前实现包含英雄别名归一、并发相同查询合并、图片缓存与实时 ARAM 页面解析。具体解析修复与上游变化记录见 `CHANGELOG.md`。

### LOL 封禁

```http
GET /lolban?qq={QQ号}&output=text|json
GET /api/v2/lolban?qq={QQ号}&output=text|json
```

机器人/插件接入主要使用 v2 兼容接口。实时 Provider 全部失败时，可在配置的 stale cache 窗口内返回最近一次成功结果。

## 6178 控制台

`master` 当前包含以下独立页面：

```text
/                         控制台总览
/query-console/lolban     封号 Provider 配置与实时诊断
/parser-center            接口与解析中心
/parser-center/secrets    Secret 管理
/parser-center/advanced   解析中心高级能力
/main-config              主接口配置
/lanzou/config            蓝奏全局配置
/lanzou/watchers          蓝奏监控项目
/lanzou/targets           通知目标
/api-debugger             接口调试器
/logs                     日志中心
/diagnostics              诊断中心
/system                   安全、服务与回滚
```

旧 `/?tab=...` 入口保留兼容重定向，但新开发和运维应优先使用独立页面。

页面壳可公开加载；涉及配置、Secret、服务控制、回滚等管理 API 时，继续受本机回环限制或 `WEBUI_ADMIN_TOKEN` 保护。真实 Secret 不应回显到页面、Provider JSON、日志或诊断结果。

## LOL 封禁 Provider 与 Secret

当前控制台支持多 Provider，核心规则是：

- 主接口：使用 `LOLMAP_API_TOKEN`；
- LOL2099：免费备用，不需要 Token；
- 4PNG：收费备用，使用 `LOL_BAN_4PNG_TOKEN`；
- 两个备用 Provider 默认关闭，避免无意消耗次数；
- 推荐顺序：主接口 → LOL2099 → 4PNG；
- Secret 在对应 Provider 卡片附近管理，保存时不回显真实值；
- 支持受控热加载到 5001，避免“磁盘已保存但运行进程未加载”的假成功状态；
- Provider 返回广告、次数上限、未知业务状态等内容时，不应当作正常查询结果发送给用户。

具体管理 API、Schema、备份与回滚行为以当前控制台实现和 `CHANGELOG.md` 为准。

## 6178 蓝奏监控接口

基础接口包括：

```text
GET  /health
GET  /watchers
GET  /events
POST /scan
POST /scan?watcher_id={id}
POST /notify/test
```

详细配置与 SnowLuma 回调格式见：

```text
lanzou_update_push_api_server/README.md
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

发布或部署前还应执行仓库当前 CI / PowerShell / WebUI JavaScript 检查，不能只以单个接口能打开作为“部署成功”。

## 维护资料

- `CHANGELOG.md`：生产功能与重要修复时间线；
- `PROJECT_INDEX.md`：项目结构、运维入口和 AI 接手索引；
- `SERVICE_RUNBOOK.md`：Windows 服务与故障处理手册；
- `lanzou_update_push_api_server/README.md`：6178 蓝奏监听服务说明；
- `AGENTS.md`：仓库开发与 AI 执行约定。

## 维护原则

- `master` 是当前默认开发分支；
- 真实运行状态以目标机器健康端、`/build-info` 和部署验证报告为准；
- 不提交账号、密码、Token、Cookie、浏览器登录态和本机运行数据；
- 不同时启动多套 5001 / 6178 实例；
- Provider、上游页面和第三方接口随时可能变化，涉及生产判断时优先查看最新代码、测试和 `CHANGELOG.md`，不要沿用旧截图或旧接口假设。
