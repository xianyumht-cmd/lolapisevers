# lolapisevers 项目索引

## 项目定位

`lolapisevers` 是一个 Windows 本地运行的英雄联盟数据接口服务，基于 `FastAPI + MySQL + Playwright + LCU API`。

它主要提供：

1. 本地 LCU 战绩采集与查询。
2. so1 站点驱动的跨区查询与快照回退。
3. 分片、极地大乱斗强化等衍生查询能力。
4. JSON、pretty、image、svg 等输出形式，供机器人或其他本地服务调用。

## 核心入口

- `app.py`：FastAPI 主入口，包含应用初始化、路由、输出格式构建和 uvicorn 启动。
- `so1_client.py`：so1 查询客户端，负责浏览器、登录态、页面抓取与解析。
- `lcu_client.py`：本地 LCU 客户端。
- `collector.py`：采集逻辑。
- `db.py`：MySQL 初始化与数据访问。
- `cache.py`：TTL 缓存。
- `requirements.txt`：Python 依赖。

## 运维脚本

- `run_server.bat`：手动启动入口，设置 `APP_PORT=5001` 后运行 `app.py`。
- `start_hidden.vbs`：隐藏窗口启动入口。
- `ops/run_service.ps1`：Windows 服务启动脚本，会加载 `ops/app_env.ps1`，再启动 Python。
- `ops/install_persistence.ps1`：安装/重装 NSSM 服务和定时保活任务。
- `ops/keepalive.ps1`：定时保活检测脚本。
- `ops/health_check.ps1`：只读体检脚本，用于检查服务、端口、健康接口和日志。
- `ops/app_env.ps1`：本机环境变量配置文件。可能包含账号、密码、路径，不应提交真实敏感值。

## 当前推荐运行方式

推荐让 `LOLDataSystem` Windows 服务作为唯一正式入口运行接口。

目标状态：

```text
LOLDataSystem / NSSM -> powershell.exe -> ops/run_service.ps1 -> .venv\Scripts\python.exe app.py
```

当前服务已经验证可以正常监听：

```text
http://127.0.0.1:5001/health
```

如果后续追求更干净的进程结构，可以再升级为：

```text
LOLDataSystem / NSSM -> .venv\Scripts\python.exe app.py
```

但在环境变量没有完全整理前，不建议直接跳过 `ops/run_service.ps1`。

## 已知重点风险

1. 不要同时使用 `run_server.bat`、`start_hidden.vbs`、NSSM 服务三套方式启动同一个 `5001` 接口。
2. 如果 5001 已被一个 Python 占用，服务再次启动会出现 `[Errno 10048]` 端口占用错误。
3. `ops/app_env.ps1` 可能包含账号密码，不应把真实值提交到仓库。
4. `logs/`、`.venv/`、`ms-playwright/`、`.so1_state.json`、`.so1_token.txt` 不应提交。
5. `app.py` 已经承担较多职责，后续可以拆分为 routers / services / renderers / schemas。

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
