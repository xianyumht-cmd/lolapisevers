# Latest handoff

更新时间：2026-08-06 02:43 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。新 V3 目标已在 Windows 生产机安全部署成功，当前只剩五个 P3B 页面、旧 `?tab=` 重定向和实际页面操作验收。

## 当前真实状态

- 当前生产：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- Windows 服务：Running
- 部署结果：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`
- Issue #40 保持打开
- Draft PR #41 保持 Draft，页面实机验收完成前禁止合并

生产备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-023757-full-bug-repair-7524a5ea36b5`

生产验证报告：

- `D:\project2\lolapisevers.deploy-backups\20260806-023757-full-bug-repair-7524a5ea36b5\verification-report.json`

## Windows 生产部署结果

目标提交：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`

部署器完成：

- release.bundle 完整性验证：PASS
- Python 3.14 离线候选环境：PASS
- 343 项候选测试：PASS
- WebUI JavaScript 语法：PASS
- 停服前健康基线采集：PASS
- 跟踪源码切换：PASS
- 已测试虚拟环境安装：PASS
- Windows 服务启动：PASS
- 后置生产验证：PASS
- 未触发自动回滚

生产验证检查：

- `windows_service`：pass，Running
- `/livez`：HTTP 200
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated
- `/readyz`：HTTP 200
- build-info：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- Git HEAD：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- shard 正式交付：`kind=segments`
- ARAM 正式交付：`kind=segments`
- observability 门禁：pass；业务观测摘要仍显示 `status=degraded`，不影响本次部署通过

停服前基线记录的是旧生产 `7d637b90...`，这是预期行为。该基线当时已经是 `ready=true`、MySQL up、Chromium up、SO1 session authenticated。

## 已完成的 P3B 页面

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。

## 当前下一步

1. 浏览器对 6178 页面执行 Ctrl + F5。
2. 提交五个 P3B 页面截图。
3. 验收五个旧 `?tab=` 地址是否跳转到新页面。
4. 实际验证主接口配置读取、保存、备份和重启提示。
5. 实际验证蓝奏配置覆盖状态、Watcher 密码掩码往返、通知 Header 脱敏与测试推送。
6. 实际验证接口调试器 Path、Query、Header、JSON Body 和结果展示。
7. 页面与操作验收通过后，标记 P3B 完成，再审查退休 `ui_control.py`、`ui_runtime.py`、旧导航注入和 `/legacy-ui`。
8. 整体迁移完成前，PR #41 保持 Draft，Issue #40 保持打开。

## 禁止再次部署的旧目标

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
