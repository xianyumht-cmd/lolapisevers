# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 交接

更新时间：2026-08-06 02:15 +08:00

## 当前断点

SO1 readiness 原始原因漂移误回滚已经修复，新 V3 不可变离线部署包已通过标准 CI、V3 构建和本地二次复核。当前下一步是 Windows 生产部署及 P3B 五个页面实机验收。

继续任务时先读取：

1. `docs/HANDOFF_LATEST.md`
2. 本文档
3. `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`

## 当前真实状态

- 仓库：`xianyumht-cmd/lolapisevers`
- Issue：#40，保持打开
- Draft PR：#41，保持 Draft，禁止合并
- 功能分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- 生产仍是 P3A，P3B 尚未部署

P3A 已在 Windows 生产机通过实机验收：333 项测试、Windows 服务、`/livez`、`/readyz`、build-info、Git HEAD、合集和 ARAM 正式链路通过。

## P3B 页面

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。共享控制台 Shell、Secret 脱敏、Watcher 密码掩码往返、通知 Header 掩码往返、本机回环或 `WEBUI_ADMIN_TOKEN` 保护均已实现。

## 已回滚部署记录

旧目标：

- `292b43ef439b6102fd34b3c7b198cc7671b65eab`

Windows 实机结果：

- release bundle 与候选环境：PASS
- Python 3.14 离线依赖：PASS
- 341 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线采集：PASS
- 生产切换与服务启动：PASS
- 后置验证：FAIL
- 自动回滚：PASS
- 恢复提交：`7d637b90ac2b177de86bae024713ac9172bb26fa`

失败原因：

```text
Post-switch SO1 session is down and does not match the pre-switch degradation baseline.
DEPLOYMENT FAILED, AUTOMATIC ROLLBACK SUCCEEDED.
```

旧验证器使用 SO1 `reason|error_class` 原始文字作为等价指纹；浏览器在线、会话仍不可用时，原因可能在 `TimeoutError`、`session_expired_or_challenge` 等值间漂移，从而误判状态恶化。

旧目标 `292b43ef...` 禁止再次部署。

## 最终归一化规则

- `so1_browser=up` 且 `so1_session!=authenticated` 时，归一化指纹为 `browser_up|session_unavailable`
- 原始 `reason|error_class` 保留为前后 verification detail
- 原始 detail 不作为同一稳定状态的唯一等价条件
- 部署前会话已认证、部署后失效：失败并回滚
- MySQL 回归：失败并回滚
- SO1 Chromium 回归：失败并回滚
- 服务、Git HEAD、build-info、正式交付链路回归：失败并回滚
- 仅部署前后均为相同受控会话不可用状态时，允许 `pass_with_warning`
- 继承降级时 `/readyz` 仍必须为 HTTP 503
- 报告必须写入 `inherited_so1_session_degradation=true`

这不是忽略 `/readyz`，而是用稳定服务状态判断是否发生新回归，同时保留原始原因用于审计。

## 最终候选与部署目标

最终候选：

- `3dadd4c782c0a44a6a3c337c5216a0f211387d46`

最终部署目标：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`
- 第一父提交：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- 第二父提交：`3dadd4c782c0a44a6a3c337c5216a0f211387d46`
- 目标 tree：`52ecd2090beb682d8114def3b79c8ed6b85887cd`
- 候选 tree：`52ecd2090beb682d8114def3b79c8ed6b85887cd`
- 零文件差异：PASS

## CI 与 V3 构建

最终候选标准验证：

- tests Run `31032837203`：success
- Linux：success
- Windows：success
- dependency audit：success
- Parser Center Run `31032836682`：success

最终目标：

- 标准 tests：success
- Parser Center：success
- V3 Run：`31033170851`，success
- V3 Job：`92398630356`
- Artifact：`8941607500`
- 临时 Draft PR #54 已关闭，未合并 master

## 制品

外层 Artifact：

- SHA-256：`883cebd0e826c35729ba7db41a17672094008a9077a22c0e95d4f58b73471b18`

内层 ZIP：

- 文件名：`LOLDataSystem-full-bug-repair-safe-deploy-7524a5ea36b5-py311-py314-winps51-v3.zip`
- SHA-256：`5ca66551f54a2adaaf66c732f0703e1e1aa11bf313b489845e1e5493e574c3c0`
- 大小：`85,842,369` 字节
- Package content SHA-256：`c8702c381f9e5c97a10ffc0318356ccb0ed638ec4d1462200c9e895245fc9fee`
- 支持 Python：3.11、3.12、3.13、3.14
- Package revision：3
- `powershell_utf8_parse_input=true`
- `baseline_aware_readiness=true`

## 本地复核

- 外层 Artifact digest：PASS
- metadata 与内层 ZIP：PASS
- manifest 51 个文件逐一哈希和大小：PASS
- Package content digest：PASS
- 归一化 SO1 指纹：PASS
- 原始 detail 审计：PASS
- MySQL、Chromium、已认证会话与 readyz 回归门禁：PASS
- 停服前基线采集：PASS
- 自动回滚：PASS
- release.bundle 完整历史：PASS
- 当前生产直接第一父提交：PASS
- 目标与候选零差异：PASS
- 临时补丁与临时工作流清理：PASS

## 下一步

1. 解压目标 `7524a5ea...` 的内层 ZIP。
2. 双击 `run-deploy.cmd`。
3. 保留完整窗口输出。
4. 提交备份目录中的 `pre-switch-health.json` 和 `verification-report.json`。
5. 部署后 Ctrl + F5 验收五个 P3B 页面。
6. 验收五个旧 `?tab=` 307 重定向。
7. 检查合集和 ARAM 正式链路。
8. 若为 `pass_with_warning`，确认唯一降级是 `inherited_so1_session_degradation`，并核对 detail 仅为会话失败原因漂移。
9. P3B 验收前不合并 PR #41，不关闭 Issue #40。

## 禁止部署

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
