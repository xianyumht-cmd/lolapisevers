# Latest handoff

更新时间：2026-08-06 03:44 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。三个首轮页面缺口的修复目标已经在 Windows 生产机安全部署并完成截图复验；页面显示层修复通过。当前只剩旧 `?tab=` 跳转和实际保存、掩码往返、测试推送、接口调试请求等操作验收。

## 当前真实状态

- 当前生产：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- Windows 服务：Running
- 部署结果：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated
- `/readyz`：HTTP 200
- shard 与 ARAM 正式交付：`kind=segments`
- Issue #40 保持打开
- Draft PR #41 保持 Draft，P3B 操作验收完成前禁止合并

生产备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-033214-full-bug-repair-dda1c27453eb`

生产验证报告：

- `D:\project2\lolapisevers.deploy-backups\20260806-033214-full-bug-repair-dda1c27453eb\verification-report.json`

## 最新 Windows 部署结果

目标：

- `dda1c27453eb3b4cf0b79a53ff043369f7662736`

结果：

- release.bundle 完整性：PASS
- Python 3.14 离线候选环境：PASS
- 345 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线：PASS
- 生产源码切换：PASS
- 服务启动：PASS
- 后置生产验证：`pass`
- 自动回滚：未触发
- build-info 与 Git HEAD：目标提交

停服前基线记录的是旧生产 `7524a5ea36b53a4186a1934edb69b691af56ac09`，当时已经 `ready=true`、MySQL up、SO1 browser up、SO1 session authenticated。

## 三个页面缺口复验

### `/lanzou/config`

- 不再直接显示连续问号模板
- 页面显示“检测到历史 WebUI 编码损坏”的保护提示
- 模板输入框保持为空并提示只有输入新内容才替换
- 该行为符合用户确认：机器人实际通知一直正常，修复不得改写真实运行模板

### `/lanzou/targets`

- 回调 URL 中敏感查询值显示为 `%2A%2A%2A`
- Header Secret 显示为 `***`
- 页面未暴露真实 token

### `/api-debugger`

- 已出现“请求 Headers JSON”输入区
- 接口清单仍正常加载 69 个接口
- 页面布局和响应区正常

因此三个首轮截图缺口的显示层验收已通过。

## P3B 尚未完成的实际操作验收

1. 验收五个旧 `?tab=` 地址是否 307 跳转到新页面。
2. 主接口配置执行一次无害保存，确认自动备份和重启提示。
3. 蓝奏全局配置在通知模板留空的情况下保存，确认真实机器人通知不被覆盖。
4. Watcher 保存一次未改密码的记录，确认掩码往返保留原密码。
5. 通知目标保存一次未改 URL Secret/Header Secret 的记录，确认真实值被保留。
6. 执行一次通知目标测试推送，确认实际机器人收到正常通知。
7. 接口调试器对安全只读接口发送一次请求，并验证 Header JSON、Query、响应展示。
8. 上述通过后标记 P3B 完成，再审查退休 `ui_control.py`、`ui_runtime.py`、旧导航注入和 `/legacy-ui`。

## 禁止再次部署的旧目标

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
- `7524a5ea36b53a4186a1934edb69b691af56ac09` 不含本轮三个页面修复，不再用于后续验收部署
