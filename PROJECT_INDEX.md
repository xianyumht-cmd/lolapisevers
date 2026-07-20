# lolapisevers 项目索引

## 项目定位

`lolapisevers` 是一个 Windows 本地运行的英雄联盟数据接口服务，基于 `FastAPI + MySQL + Playwright`。

它主要提供：

1. so1 站点驱动的跨区查询与 MySQL 快照回退。
2. 英雄碎片、极地大乱斗强化和 LOL 封禁等查询能力。
3. JSON、pretty、image、svg 等输出形式，供机器人或其他本地服务调用。
4. 独立的蓝奏云更新监控与 SnowLuma 通知能力。

## 核心入口

- `app.py`：FastAPI 主入口，负责创建应用、挂载路由和启动 uvicorn。
- `so1_client.py`：so1 查询客户端，负责浏览器、登录态、页面抓取与解析。
- `core/`：配置、应用上下文与生命周期。
- `routers/`：当前 HTTP 路由和参数校验。
- `services/`：查询、上游请求、数据清洗、快照与业务缓存。
- `renderers/`：PNG/SVG 输出渲染。
- `db.py`：MySQL 初始化与数据访问。
- `cache.py`：TTL 缓存。
- `requirements.txt`：Python 依赖。

## 运维脚本

- `run_server.bat`：手动启动入口，通过 `ops/run_service.ps1` 加载本机配置并启动服务。
- `start_hidden.vbs`：隐藏窗口启动入口。
- `ops/run_service.ps1`：Windows 服务启动脚本，会加载本机专用的 `ops/app_env.local.ps1`，再启动 Python。
- `ops/install_persistence.ps1`：安装/重装 NSSM 服务和定时保活任务。
- `ops/keepalive.ps1`：定时保活检测脚本。
- `ops/health_check.ps1`：只读体检脚本，用于检查服务、端口、健康接口和日志。
- `ops/app_env.example.ps1`：可提交的安全配置模板，只能保留占位值。
- `ops/app_env.local.ps1`：由模板复制得到的本机配置，已被 Git 忽略，不应提交真实敏感值。

## 当前推荐运行方式

推荐让 `LOLDataSystem` Windows 服务作为唯一正式入口运行接口。

首次运行先创建不会提交到 Git 的本机配置：

```powershell
Copy-Item .\ops\app_env.example.ps1 .\ops\app_env.local.ps1
```

填写本机值后，通过 `run_server.bat` 或 `ops/run_service.ps1` 启动；直接执行 `python app.py` 不会自动加载该 PowerShell 配置。

目标状态：

```text
LOLDataSystem / NSSM -> powershell.exe -> ops/run_service.ps1
  -> python app.py                            (5001)
  -> python -m lanzou_update_push_api_server (6178)
```

当前服务已经验证可以正常监听：

```text
http://127.0.0.1:5001/health
```

`ops/run_service.ps1` 同时负责加载本机环境变量和启动两个进程，不应直接绕过。

## 已知重点风险

1. 不要同时使用 `run_server.bat`、`start_hidden.vbs`、NSSM 服务三套方式启动同一个 `5001` 接口。
2. 如果 5001 已被一个 Python 占用，服务再次启动会出现 `[Errno 10048]` 端口占用错误。
3. `ops/app_env.local.ps1` 可能包含账号密码，不应把真实值提交到仓库；`ops/app_env.example.ps1` 只能使用占位值。
4. `logs/`、`.venv/`、`ms-playwright/`、`.so1_state.json`、`.so1_token.txt` 不应提交。
5. 直接执行 `python app.py` 不会自动加载 `ops/app_env.local.ps1`，应优先使用项目启动脚本。

## 排查优先级

当接口异常时，按这个顺序排查：

1. `curl http://127.0.0.1:5001/health`
2. `Get-Service LOLDataSystem`
3. `Get-NetTCPConnection -LocalPort 5001 -State Listen`
4. `tasklist | findstr /i "python powershell nssm"`
5. `Get-Content logs\service.stderr.log -Tail 80`
6. `Get-Content logs\service.stdout.log -Tail 80`

或者直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\health_check.ps1"
```

## 给 AI / Codex / Trae 的接手规则

1. 先读本文件，再读 `SERVICE_RUNBOOK.md`。
2. 不要猜测本机服务状态，涉及端口、服务、进程时必须让用户提供命令输出。
3. 不要直接执行破坏性命令，例如 `taskkill`、`net stop`、`nssm remove`、`git reset --hard`、`git push --force`。
4. 涉及真实账号、密码、token、cookie、登录态文件时，只能让用户打码后提供。
5. 优先做可回滚、小步提交的修改。
## Lanzou Update Push API Server

This project now also contains a local Lanzou update monitor:

```text
D:\project2\lolapisevers\lanzou_update_push_api_server
```

Purpose:

- Monitor Lanzou links from the website nav page.
- Store local snapshots in `lanzou_update_push_api_server/state.json`.
- Detect added, removed, or changed files.
- POST update events to SnowLuma.

Runtime:

```text
LOLDataSystem / NSSM
  -> ops/run_service.ps1
     -> python -m lanzou_update_push_api_server  (port 6178)
     -> python app.py                            (port 5001)
```

Important files:

- `lanzou_update_push_api_server/config.json`: local monitor config, ignored by Git.
- `lanzou_update_push_api_server/config.example.json`: safe example config.
- `lanzou_update_push_api_server/README.md`: feature and API usage.
- `ops/run_service.ps1`: starts both the monitor and the main API.
- `ops/health_check.ps1`: checks both `5001` and `6178`.
- `D:\project2\napcatplugin\lengxi_repo\napcat-plugin-groupguard\docs\LANZOU_UPDATE_PUSH.md`: SnowLuma receiver documentation.

Current nav import:

```text
source: D:\project2\website-main src/pages/nav final data
Lanzou watchers: 44
scheduled scan: 1 link per batch, 90 seconds between links
full cycle rest: 1800 seconds
```

Routine checks:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\health_check.ps1"
Invoke-RestMethod "http://192.168.3.100:6178/health"
Invoke-RestMethod "http://192.168.3.100:6178/watchers"
```
