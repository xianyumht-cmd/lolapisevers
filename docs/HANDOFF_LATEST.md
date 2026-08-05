# Latest handoff

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003`，完成 P3B 主接口配置、蓝奏配置、监控项目、通知目标和接口调试器的最终 CI、部署包和 Windows 实机验收。

当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`。

P3A 已在 Windows 生产机安全部署并通过实机验收：333 项测试、Windows 服务、`livez`、`readyz`、build-info、Git HEAD、合集和 ARAM 正式交付链路均通过，verification report 为 `pass`。

P3B 功能提交：`3c7a8868020eecee9cffbfca70d96e2766ba8f5c`，已完成分支实现但尚未部署生产：

- `/main-config`：主接口配置；
- `/lanzou/config`：蓝奏全局配置；
- `/lanzou/watchers`：监控项目；
- `/lanzou/targets`：通知目标；
- `/api-debugger`：接口调试器；
- 对应旧 `?tab=` 地址全部改为 307 兼容重定向；
- 新页面使用共享控制台 Shell、`configuration.css/js` 和本地 SVG 图标；
- Secret、Watcher 密码和通知 Header 均支持脱敏与掩码往返保留；
- 页面壳公开，管理 API 继续受本机回环或 `WEBUI_ADMIN_TOKEN` 保护；
- 不使用浏览器原生 `alert`、`confirm` 或 `prompt`。

P3B 功能补丁形成提交前已通过：

- 补丁完整性和精确大小 91,523 字节；
- `git apply --check`；
- Python 编译；
- 338 项测试；
- 最终页面资源检查；
- `configuration.js` 语法检查；
- 临时补丁与工作流自动清理；
- 正式 `tests.yml` 恢复。

下一步：等待本次文档提交触发的标准 Linux、Windows、Parser Center、所有 WebUI JavaScript、PowerShell 5.1 和依赖审计全部通过；随后以当前生产为第一父提交生成 P3B V3 不可变一键部署包。PR #41 保持 Draft，Issue #40 保持打开。
