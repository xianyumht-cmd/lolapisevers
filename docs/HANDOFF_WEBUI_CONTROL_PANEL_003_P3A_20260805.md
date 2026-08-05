# WEBUI-CONTROL-PANEL-003 P3A 交接：日志、诊断、安全与回滚独立页面

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`3d0ddd7e76123660409ddaaf74b641641d282ee4`
- 日期：2026-08-05

## 1. 为什么开始 P3A

P0 实机验收确认新总览可用，但进一步审查发现 6178 仍存在三套前端：

1. `/` 与 `/ui`：新的共享控制台总览；
2. `/?tab=...`：旧全功能运行面板，仍承载日志、配置、诊断、安全等核心功能；
3. `/legacy-ui`：更早的旧控制台。

因此不能仅隐藏“旧版入口”。必须先把仍依赖旧面板的功能迁移到共享设计系统，再逐项退休旧 `?tab=` 页面。

## 2. P3A 已迁移页面

### `/logs`

- 独立共享控制台外壳；
- 日志目录、存在状态和文件大小；
- 日志选择；
- 尾部行数，范围 1–5000；
- 关键词过滤；
- 日志正文使用等宽字体；
- 继续复用 `/admin/logs` 与 `/admin/logs/{name}`。

### `/diagnostics`

- 独立共享控制台外壳；
- 诊断总数、通过数和失败数；
- 端口、JSON 文件、Python、Playwright、本地环境和 Windows 服务检查；
- 状态文件修复使用自定义确认 Dialog；
- 继续复用 `/admin/diagnostics` 与 `/admin/repair/state`。

### `/system`

- 独立共享控制台外壳；
- Windows 服务状态；
- 控制台访问策略；
- 配置备份列表；
- 配置回滚；
- 管理审计；
- Windows 服务受控重启；
- 回滚和重启均使用自定义确认 Dialog；
- 继续复用 `/security/status`、`/admin/service/status`、`/admin/service/restart`、`/admin/backups`、`/admin/rollback/{kind}` 和 `/admin/audit`。

## 3. 兼容处理

旧地址不再承载已迁移功能，而是 307 重定向：

- `/?tab=logs` → `/logs`
- `/?tab=diagnostics` → `/diagnostics`
- `/?tab=system` → `/system`

尚未迁移的地址继续保留旧功能：

- `/?tab=mainconfig`
- `/?tab=lanzouconfig`
- `/?tab=watchers`
- `/?tab=targets`
- `/?tab=debugger`

`/legacy-ui` 仍保留为隐藏的紧急回退路由，但正式菜单不展示。

## 4. 安全与交互

- 页面 HTML、CSS、JavaScript 可在启用 `WEBUI_ADMIN_TOKEN` 时正常打开；
- 管理 API 继续受令牌保护；
- 令牌只保存到当前浏览器标签页 `sessionStorage`；
- 401/403 自动打开令牌 Dialog；
- 不使用原生 `alert`、`confirm` 或 `prompt`；
- 重启、回滚和修复对 HTTP 200 里的 `ok:false` 也按失败处理，不会误报成功；
- 安全页读取真实 `token_configured`，不展示真实令牌值。

## 5. 前端结构

新增：

- `lanzou_update_push_api_server/control_ui/operations.py`
- `lanzou_update_push_api_server/control_ui/assets/operations.js`
- `lanzou_update_push_api_server/control_ui/assets/operations.css`
- `tests/test_control_ui_operations.py`

共享 Shell 现在支持每个页面指定独立 CSS 和 JavaScript，避免总览专用 `console.js` 在其他页面访问不存在的 DOM。

## 6. 自动测试

已增加：

- 三个独立页面结构与活动菜单测试；
- 页面壳公开、管理 API 受保护测试；
- 旧 `?tab=` 地址 307 重定向测试；
- `operations.js` 的 `node --check`；
- 破坏性操作必须使用 Dialog；
- 安全状态字段和 HTTP 200 / `ok:false` 处理回归测试；
- 新 SVG 图标和 Operations CSS 资源检查。

P3A 初始实现提交 `9ce588d3b3b9d4cf96352b4bc5465c8814bf69ef` 已通过 Linux、Windows、Parser Center、JavaScript、PowerShell 5.1 和依赖审计。运行逻辑加固提交为 `3024a52f2c1d63fe6f2585ae0ae4aa11aec43355`，随后由正常提交触发最终标准 CI。

## 7. 下一步

1. 最终标准 CI 全绿后，以当前生产 `3d0ddd7e...` 为直接祖先生成 V3 安全部署包；
2. 实机验收 `/logs`、`/diagnostics`、`/system`；
3. 不测试破坏性操作时，可只检查 Dialog 是否正常打开并取消；
4. 日志读取、诊断执行、备份与审计读取必须实际测试；
5. P3A 通过后开始 P3B：主接口配置、蓝奏配置、监控项目、通知目标和接口调试器迁移；
6. 所有 `?tab=` 功能迁移前，不删除 `ui_control.py`、`ui_runtime.py` 或旧面板路由。
