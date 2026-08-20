# lolapisevers 服务运行手册

## 目标状态

`lolapisevers` 推荐以 Windows 服务方式长期运行：

```text
服务名：LOLDataSystem
主 API：5001（http://127.0.0.1:5001/health）
蓝奏监控：6178（http://127.0.0.1:6178/health）
日志目录：D:\project2\lolapisevers\logs
```

当前稳定方案：

```text
NSSM -> powershell.exe -> ops\run_service.ps1
  -> .venv\Scripts\python.exe app.py
  -> .venv\Scripts\python.exe -m lanzou_update_push_api_server
```

说明：PowerShell 是启动壳，不代表异常。它负责加载本机专用的 `ops/app_env.local.ps1` 和设置默认环境变量。

**唯一入口规则：** 正式长期运行时只允许 `LOLDataSystem` 服务拥有 `ops\run_service.ps1`。`run_server.bat` 与 `start_hidden.vbs` 只用于临时手动调试，不得再配置到 Windows Startup、Run 注册表或其它登录自启位置。

## 持久化安装 / 从旧 Startup 迁移

管理员 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\install_persistence.ps1" -Apply
```

脚本会按以下顺序执行：

1. 检查当前项目是否存在非 `LOLDataSystem` 服务拥有的 `run_service.ps1` supervisor；存在时停止并报出 PID，不自动杀进程。
2. 确保 Playwright 运行时、`LOLDataSystem` NSSM 服务和 `LOLDataSystem-KeepAlive` 计划任务。
3. 验证当前恰好只有一个由服务拥有的 `run_service.ps1` supervisor。
4. 扫描所有可见本地用户 Startup 目录和 Common Startup；只处理明确指向当前项目 `start_hidden.vbs`、`run_server.bat` 或 `ops\run_service.ps1` 的启动项。
5. 命中的旧启动项不会删除，而是移动到：

```text
D:\project2\lolapisevers\logs\retired-startup\<时间戳>\
```

并保存 `manifest.json`。迁移启动项本身如果中途失败，脚本会恢复已移动的项目，避免留下半迁移状态。

## 日常检查

管理员 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\health_check.ps1"
```

核心检查项：

```powershell
curl http://127.0.0.1:5001/health
Get-Service LOLDataSystem
Get-NetTCPConnection -LocalPort 5001 -State Listen
```

正常结果应满足：

```text
/health 返回 200 OK
status = ok
mysql = up
so1_browser = up
LOLDataSystem = Running
StartType = Automatic
5001 由 python.exe 监听
Runtime topology = exactly one service-owned supervisor
legacy Startup entries = none
```

`health_check.ps1` 的 `Runtime topology` 会列出所有命中当前项目 `ops\run_service.ps1` 的 PowerShell supervisor、父 PID/父进程、是否为服务子进程，以及仍然存在的旧 Startup 启动项。拓扑告警目前单独显示，不改变 HTTP readiness 的退出码。

## 启动服务

```powershell
Start-Service LOLDataSystem
```

## 停止服务

```powershell
Stop-Service LOLDataSystem
```

## 查看服务配置

```cmd
sc queryex LOLDataSystem
sc qc LOLDataSystem
nssm get LOLDataSystem Application
nssm get LOLDataSystem AppParameters
nssm get LOLDataSystem AppDirectory
nssm get LOLDataSystem AppStdout
nssm get LOLDataSystem AppStderr
nssm get LOLDataSystem AppEnvironmentExtra
```

## 查看端口占用

```powershell
Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
  [PSCustomObject]@{
    LocalPort=$_.LocalPort
    PID=$_.OwningProcess
    ProcessName=$p.ProcessName
    Path=$p.Path
  }
} | Format-Table -AutoSize
```

## 常见故障 1：5001 端口占用 / 重复启动

现象：

```text
[Errno 10048] error while attempting to bind on address ('0.0.0.0', 5001)
```

含义：已经有另一个进程占用了 5001，新的服务实例无法启动，或者旧的登录自启链与正式服务同时存在。

先运行：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\health_check.ps1"
```

重点看：

```text
==== Runtime topology ====
```

也可以单独排查：

```powershell
Get-NetTCPConnection -LocalPort 5001 -State Listen
Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "app\.py" } | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | Format-List
```

处理原则：

1. 正式状态只保留 `LOLDataSystem` 服务。
2. 不要同时运行 `run_server.bat`、`start_hidden.vbs` 和 `LOLDataSystem` 服务。
3. 如果 `install_persistence.ps1 -Apply` 报出非服务 supervisor，先根据 PID 确认并停止那条手动/旧启动链，再重新执行安装器。
4. 如果只是残留 Startup 快捷方式而当前没有第二个 supervisor，重新执行 `install_persistence.ps1 -Apply` 会在服务验证通过后安全备份并移出该旧启动项。

## 常见故障 2：health 不通

排查：

```powershell
Get-Service LOLDataSystem
Get-NetTCPConnection -LocalPort 5001 -State Listen
Get-Content "D:\project2\lolapisevers\logs\service.stderr.log" -Tail 80
```

如果服务未运行：

```powershell
Start-Service LOLDataSystem
```

如果端口无人监听，且服务启动失败，优先查看 `service.stderr.log`。

## 常见故障 3：keepalive 一直失败

先确认 `ops\keepalive.ps1` 的 `KEEPALIVE_BASE_URL` 或默认地址是否指向：

```text
http://127.0.0.1:5001
```

如果仍失败，手动测试：

```powershell
curl http://127.0.0.1:5001/health
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\keepalive.ps1"
```

## 常见故障 4：so1_browser down

处理顺序：

1. 重启服务。
2. 检查 Playwright Chromium 是否存在。
3. 必要时重新安装浏览器运行时。

```powershell
Restart-Service LOLDataSystem
cd /d D:\project2\lolapisevers
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 不建议做的事

- 不要同时启动多套 `app.py`。
- 不要直接删除 `logs` 目录下所有文件后再排查故障。
- 不要把真实账号、密码、token 提交到仓库。
- 不要在不确认远端状态的情况下 `git push --force`。
- 不要在服务运行时反复双击 `run_server.bat`。
- 不要重新把 `start_hidden.vbs` 快捷方式加入 Startup 来“增强保险”；这会制造第二条启动链，而不是提高可靠性。

## 后续优化方向

1. 评估将长期 supervisor 从 PowerShell 壳迁移为更低开销的托管入口；在没有运行时 CPU 证据前，不把 `run_service.ps1` 的 5 秒轮询直接判定为高 CPU 根因。
2. 把环境变量整理成模板文件和本机私有文件。
3. 将 `app.py` 拆分为 `routers/`、`services/`、`renderers/`、`schemas/`。
4. 增加更明确的日志编码与日志轮转策略。
5. 增加自动化健康检查与回滚脚本。

## Lanzou Update Push API Server

`lanzou_update_push_api_server` is the local Lanzou update monitor. It runs beside the main `lolapisevers` API and sends update events to SnowLuma when watched Lanzou links change.

### Runtime

When `LOLDataSystem` starts through NSSM, it runs:

```text
LOLDataSystem -> powershell.exe -> ops/run_service.ps1
```

`ops/run_service.ps1` starts two Python processes:

```text
1. python -m lanzou_update_push_api_server  -> http://192.168.3.100:6178
2. python app.py                           -> http://127.0.0.1:5001
```

The Lanzou monitor is stopped when the parent service script exits.

### Configuration

Local config:

```text
D:\project2\lolapisevers\lanzou_update_push_api_server\config.json
```

This file is intentionally ignored by Git. It currently contains the Lanzou links extracted from the website nav page.

Important fields:

```json
{
  "scan_interval_seconds": 1800,
  "scan_batch_size": 1,
  "scan_batch_pause_seconds": 90,
  "watchers": [],
  "notify_targets": []
}
```

Meaning:

- `watchers`: Lanzou links to monitor.
- `scan_interval_seconds`: pause after one full scan cycle.
- `scan_batch_size`: number of links scanned before pausing during scheduled scans.
- `scan_batch_pause_seconds`: pause between scheduled scan batches.
- `notify_targets`: SnowLuma callback targets.

The current production-friendly setting scans one link at a time and waits 90 seconds before the next link, so the nav links are not requested all at once.

### SnowLuma Callback

SnowLuma endpoint:

```text
http://192.168.3.89:6108/api/lanzou-update/event?token=YOUR_GROUPGUARD_WEBUI_TOKEN
```

Enable the callback in `config.json` only after the SnowLuma token and target groups/private users are configured：

```json
{
  "name": "snowluma",
  "enabled": true,
  "url": "http://192.168.3.89:6108/api/lanzou-update/event?token=YOUR_GROUPGUARD_WEBUI_TOKEN",
  "headers": {
    "x-groupguard-token": "YOUR_GROUPGUARD_WEBUI_TOKEN"
  }
}
```

SnowLuma side documentation:

```text
D:\project2\napcatplugin\lengxi_repo\napcat-plugin-groupguard\docs\LANZOU_UPDATE_PUSH.md
```

### Health Check

Run:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\project2\lolapisevers\ops\health_check.ps1"
```

Expected:

```text
http://127.0.0.1:5001/health  -> ok
http://192.168.3.100:6178/health  -> ok
LOLDataSystem                 -> Running
Runtime topology              -> one service-owned supervisor
Legacy Startup                -> none
```

Manual endpoint checks:

```powershell
Invoke-RestMethod "http://192.168.3.100:6178/health"
Invoke-RestMethod "http://192.168.3.100:6178/watchers"
Invoke-RestMethod "http://192.168.3.100:6178/events"
```

Manual single-link scan:

```powershell
Invoke-RestMethod -Method Post "http://192.168.3.100:6178/scan?watcher_id=nav-029-jntm&notify=false"
```

Avoid running `POST /scan` without `watcher_id` during normal checks because it scans every configured Lanzou link immediately.

### Logs

Main API:

```text
D:\project2\lolapisevers\logs\service.stdout.log
D:\project2\lolapisevers\logs\service.stderr.log
```

Lanzou monitor:

```text
D:\project2\lolapisevers\logs\lanzou_monitor.stdout.log
D:\project2\lolapisevers\logs\lanzou_monitor.stderr.log
```

### Restart

After changing `ops/run_service.ps1` or the monitor config, restart the Windows service:

```powershell
Restart-Service LOLDataSystem
```

Then run the health check script above.
