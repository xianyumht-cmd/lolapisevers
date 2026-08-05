# WEBUI-CONTROL-PANEL-003 P3B 交接

更新时间：2026-08-06 03:52 +08:00

## 当前状态

- Issue：#40，保持打开以继续跟踪整体 WebUI 迁移；
- Draft PR：#41，整体迁移完成前保持 Draft；
- 分支：`feat/webui-control-panel-003-20260805`；
- 当前生产：`dda1c27453eb3b4cf0b79a53ff043369f7662736`；
- P3B 状态：**已完成并关闭阶段任务**。

## 已迁移页面

- `/main-config`：主接口配置；
- `/lanzou/config`：蓝奏全局配置；
- `/lanzou/watchers`：监控项目；
- `/lanzou/targets`：通知目标；
- `/api-debugger`：接口调试器。

兼容重定向：

- `/?tab=mainconfig` → `/main-config`；
- `/?tab=lanzouconfig` → `/lanzou/config`；
- `/?tab=watchers` → `/lanzou/watchers`；
- `/?tab=targets` → `/lanzou/targets`；
- `/?tab=debugger` → `/api-debugger`。

## 生产部署与验证

最终生产目标：

- `dda1c27453eb3b4cf0b79a53ff043369f7662736`

实机结果：

- 345 项候选测试：PASS；
- Windows 服务：Running；
- `/livez`：HTTP 200；
- `/readyz`：HTTP 200；
- MySQL：up；
- SO1 Chromium：up；
- SO1 session：authenticated；
- build-info 与 Git HEAD：目标提交；
- shard 与 ARAM：`kind=segments`；
- verification：`pass`；
- `degraded=false`；
- `inherited_so1_session_degradation=false`；
- 自动回滚：未触发。

## 最终验收

- 五个新页面均可正常打开；
- 统一 Sidebar、Topbar、面包屑、状态提示和管理令牌组件正常；
- 主接口配置保存、自动备份和重启提示正常；
- 蓝奏配置保存和热更新正常；
- 历史 WebUI 乱码模板已采用保护显示，留空保存不会覆盖机器人实际模板；
- Watcher 密码掩码往返正常；
- 通知目标 URL 查询 Secret 和 Header Secret 脱敏正常；
- 通知目标未修改掩码直接保存可保留真实值；
- 测试推送正常，机器人收到中文正常的测试通知；
- 接口调试器支持 Query、Path、Headers JSON、JSON Body；
- `GET /admin/audit?limit=100` 实机调用返回 HTTP 200；
- 用户最终确认剩余测试正常。

## 安全边界

- Secret 不回显；
- 空白或 `***` 表示保留原值；
- URL 查询参数掩码保存时仅在 scheme、host、path 不变的条件下恢复旧值；
- 目标地址变化时不静默复用旧 Secret；
- 调试器禁止 Host、Content-Length 和 hop-by-hop Header；
- 内部管理令牌由服务端安全注入，不能由页面覆盖；
- 请求与响应中的敏感 URL/Header 值会脱敏；
- 管理 API 继续受本机回环或 `WEBUI_ADMIN_TOKEN` 保护。

## 阶段关闭结论

P3B 的实现、CI、部署、截图和操作验收均已完成。此阶段不再继续修改或重复部署。

下一阶段：

1. 审查 `ui_control.py`、`ui_runtime.py`；
2. 盘点旧导航注入仍承载的入口；
3. 审查 `/legacy-ui` 是否仍有生产依赖；
4. 迁移遗漏功能后，分批退休旧代码和旧入口；
5. 整体 WebUI 迁移完成后再决定 PR #41 合并和 Issue #40 关闭。
