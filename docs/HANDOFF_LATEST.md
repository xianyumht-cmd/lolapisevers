# Latest handoff

更新时间：2026-08-06 02:02 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。部署目标 `292b43ef...` 已在 Windows 生产机执行，但后置验证仍因 SO1 原始失败原因字符串变化而安全回滚。归一化状态修复已经形成候选，当前等待标准 CI 与新的 V3 不可变离线部署包。

## 当前真实状态

- 当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- 自动回滚成功，生产仍是已通过实机验收的 P3A
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

## `292b43ef...` Windows 部署结果

旧部署目标：

- `292b43ef439b6102fd34b3c7b198cc7671b65eab`

实机执行结果：

- release bundle、候选环境和 Python 3.14 离线依赖安装：PASS
- 341 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线采集：PASS
- 切换到目标提交并启动服务：PASS
- 后置验证：FAIL
- 自动回滚：PASS
- 恢复生产提交：`7d637b90ac2b177de86bae024713ac9172bb26fa`

失败信息：

```text
Post-switch SO1 session is down and does not match the pre-switch degradation baseline.
DEPLOYMENT FAILED, AUTOMATIC ROLLBACK SUCCEEDED.
```

该包已经完成一次实机失败验证，禁止再次部署。

## 新根因

`292b43ef...` 的验证器以 SO1 `reason|error_class` 原始字符串作为失败指纹。

SO1 Chromium 浏览器在部署前后均为 `up`、SO1 会话在部署前后均为未认证时，探测原因仍可能在 `TimeoutError`、`session_expired_or_challenge` 等值之间波动。原验证器因此把“同一个会话不可用状态下的原因文字变化”误判为依赖状态恶化。

这不是放宽真实回归门禁的问题，而是指纹层级选错：应比较稳定的服务状态，同时保留原始原因用于审计。

## 已完成的归一化修复

当前候选提交：

- `b213d0a6c66e2dc4877d070d5b5721fa5ea04b92`

修复规则：

- 当 `so1_browser=up` 且 `so1_session!=authenticated` 时，归一化指纹为 `browser_up|session_unavailable`
- 原始 `reason|error_class` 不参与等价判断，但会作为前后 detail 写入 verification report
- 部署前会话已认证、部署后失效：仍强制失败并回滚
- MySQL 回归：仍强制失败并回滚
- SO1 Chromium 浏览器回归：仍强制失败并回滚
- 部署前后均为受控的会话不可用状态：允许 `pass_with_warning`
- `/readyz` 在继承降级时仍必须保持 HTTP 503
- `/livez`、build-info、Git HEAD 和正式交付链路门禁不变

临时补丁门禁已经通过：

- 补丁 CRLF checkout SHA-256 与字节数：PASS
- `git apply --check --whitespace=error-all`：PASS
- 完整 Windows 安全门测试：PASS
- 全部单元测试：PASS
- 全部 WebUI JavaScript：PASS
- 依赖审计：PASS
- Windows PowerShell 5.1：PASS
- 临时补丁与临时工作流已清理
- 正式 `tests.yml` 已恢复

## 当前下一步

1. 等待候选 `b213d0a6...` 的标准 Linux、Windows、Parser Center 和依赖审计 CI 全绿。
2. 以当前生产 `7d637b90...` 为第一父提交，创建新的部署目标。
3. 验证新部署目标与最终候选零文件差异。
4. 创建新的 `[DO NOT MERGE]` 临时 Draft PR 触发 V3 构建。
5. 完成 Artifact、内层 ZIP、metadata、manifest 51 文件、release.bundle、祖先链和安全标志本地复核。
6. 只向用户交付新的部署包；禁止再次使用 `292b43ef...`。
7. Windows 实机部署后，依据完整控制台输出、`pre-switch-health.json`、`verification-report.json` 和五个页面截图验收。
8. P3B 实机验收前，不合并 PR #41，不关闭 Issue #40。

## 禁止部署目标

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
