# Latest handoff

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B，修复 V3 构建器中 `Verify-FullBugRepairDeployment.ps1` readyz 区块的 CRLF/LF 多行锚点匹配问题，重新构建基线感知 readiness 的 Windows 离线一键部署包。

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

基线感知 readiness 逻辑已实现：部署前保存健康基线，只允许 SO1 会话依赖在部署前后保持完全相同的既有降级；新增或恶化的降级仍必须失败并回滚。

当前构建器候选：

- `5df00bb8e0763972294fde9443f26436c42b2320`

该候选已经通过 Linux、Windows、Parser Center、341 项测试、全部 WebUI JavaScript、17 个 PowerShell 脚本的 Windows PowerShell 5.1 解析和依赖安全审计。

## 当前阻塞

第二次 V3 构建目标：

- `954f7748d41da9c3264441d33d60b7c9273fd946`
- 临时 Draft PR #50，禁止合并
- V3 Run `31020489861`
- Job `92355626999`

不可变测试、PowerShell 5.1 和依赖审计均通过，但 ZIP 构建失败：

```text
Verifier readyz block anchor was not unique.
```

失败位置在 `ops/Build-FullBugRepairPackageV3.ps1` 约第 325 行。根因与前一次部署调用锚点相同：Windows PowerShell 5.1 here-string 为 CRLF，被扫描验证脚本为 LF，多行锚点未标准化。

没有上传制品，没有可部署 ZIP。以下两个目标均禁止部署：

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`

## 新对话第一步

修复 Verifier readyz block 锚点：先把查找锚点和替换文本标准化为 LF，再继续要求精确匹配一次；不要放宽唯一性安全门。更新回归测试后跑完整标准 CI，再创建新的生产第一父提交目标和新的 `[DO NOT MERGE]` V3 构建 PR。
