# Latest handoff

更新时间：2026-08-06 02:15 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。SO1 readiness 原始原因漂移误回滚已经修复，新 V3 不可变离线部署包已构建并完成本地复核，当前等待 Windows 生产机部署与五个 P3B 页面实机验收。

## 当前真实状态

- 当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- 生产仍是已通过实机验收的 P3A
- P3B 尚未部署生产
- Issue #40 保持打开
- Draft PR #41 保持 Draft，禁止合并

P3B 五个页面已完成：

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。

## 已回滚的旧包

部署目标 `292b43ef439b6102fd34b3c7b198cc7671b65eab` 已在 Windows 实机执行：候选 341 项测试、切换和服务启动通过，但后置验证以 SO1 `reason|error_class` 原始字符串作为指纹，因同一会话不可用状态下原因文字变化而误判回归。

自动回滚成功，恢复生产提交 `7d637b90...`。该旧包禁止再次部署。

## 最终归一化 readiness 规则

- 当 `so1_browser=up` 且 `so1_session!=authenticated` 时，稳定指纹为 `browser_up|session_unavailable`
- 原始 `reason|error_class` 继续写入 verification detail，用于审计但不作为同一状态的唯一判断依据
- 部署前会话已认证、部署后失效：失败并回滚
- MySQL 回归：失败并回滚
- SO1 Chromium 回归：失败并回滚
- 服务、Git HEAD、build-info 或正式交付链路回归：失败并回滚
- 只有部署前后均为同一受控会话不可用状态时，允许 `pass_with_warning`
- 继承降级时 `/readyz` 仍必须是 HTTP 503
- 报告必须写入 `inherited_so1_session_degradation=true`

## 最终候选与新部署目标

最终候选：

- `3dadd4c782c0a44a6a3c337c5216a0f211387d46`

新 V3 部署目标：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`
- 第一父提交：当前生产 `7d637b90ac2b177de86bae024713ac9172bb26fa`
- 第二父提交：最终候选 `3dadd4c782c0a44a6a3c337c5216a0f211387d46`
- 目标与候选 tree 均为 `52ecd2090beb682d8114def3b79c8ed6b85887cd`
- 目标与候选零文件差异

## CI 与 V3 构建

提交 `3dadd4c...` 标准验证：

- tests Run `31032837203`：success
- Linux：success
- Windows：success
- dependency audit：success
- LAPI Parser Center CI Run `31032836682`：success

新部署目标 `7524a5ea...`：

- 标准 tests：success
- LAPI Parser Center CI：success
- V3 Build Run：`31033170851`，success
- V3 Job：`92398630356`
- Artifact：`8941607500`
- 临时 Draft PR #54 已关闭，未合并 master，未自动部署生产

旧非 V3 打包工作流失败不作为交付依据；只使用成功的 V3 Artifact。

## 新制品信息

外层 Artifact：

- SHA-256：`883cebd0e826c35729ba7db41a17672094008a9077a22c0e95d4f58b73471b18`

内层部署 ZIP：

- 文件名：`LOLDataSystem-full-bug-repair-safe-deploy-7524a5ea36b5-py311-py314-winps51-v3.zip`
- SHA-256：`5ca66551f54a2adaaf66c732f0703e1e1aa11bf313b489845e1e5493e574c3c0`
- 大小：`85,842,369` 字节
- Package content SHA-256：`c8702c381f9e5c97a10ffc0318356ccb0ed638ec4d1462200c9e895245fc9fee`
- Package revision：3
- 支持 Python：3.11、3.12、3.13、3.14
- `powershell_utf8_parse_input=true`
- `baseline_aware_readiness=true`

## 本地二次复核

- 外层 Artifact SHA-256 与 Actions digest：PASS
- metadata 中内层 ZIP 名称、哈希和大小：PASS
- manifest 51 个文件逐一大小和 SHA-256：PASS
- Package content SHA-256：PASS
- SO1 归一化指纹 `browser_up|session_unavailable`：PASS
- 原始 failure detail 审计：PASS
- MySQL、Chromium、已认证会话与 readyz 真实回归门禁：PASS
- 停服前 `pre-switch-health.json` 采集：PASS
- 自动回滚门禁：PASS
- `release.bundle` 完整历史：PASS
- 当前生产是目标直接第一父提交：PASS
- 目标与最终候选零文件差异：PASS
- 临时补丁与临时工作流不存在于目标树：PASS

## 下一步

1. 只使用目标 `7524a5ea...` 的新 ZIP，解压后双击 `run-deploy.cmd`。
2. 保留完整部署窗口输出。
3. 提交备份目录中的 `pre-switch-health.json` 和 `verification-report.json`。
4. 部署成功后按 Ctrl + F5，实机验收五个 P3B 页面和五个旧 `?tab=` 重定向。
5. 检查合集与 ARAM 正式交付链路。
6. 若结果是 `pass_with_warning`，必须确认唯一降级是 `inherited_so1_session_degradation`，并检查 SO1 detail 仅为原因漂移；MySQL、Chromium、服务、Git HEAD、build-info 和正式链路必须通过。
7. P3B 实机验收前，不合并 PR #41，不关闭 Issue #40。

## 禁止部署目标

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
