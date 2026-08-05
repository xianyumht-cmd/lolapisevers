# Latest handoff

更新时间：2026-08-06 01:20 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。基线感知 readiness 修复和 V3 不可变离线一键部署包已经完成，当前等待 Windows 生产机部署与五个 P3B 页面实机验收。

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

## 已完成的 readiness 修复

最初 P3B 部署失败不是 P3B 页面或服务启动回归，而是部署前就已存在 SO1 登录会话探测超时，旧验证器把既有降级误判成候选引入的新故障。

当前验证规则已经改为基线感知：

- 停服前保存 `pre-switch-health.json`
- MySQL 或 SO1 Chromium 浏览器出现新回归时仍强制失败并回滚
- 部署前 SO1 会话正常、部署后失效时仍强制失败并回滚
- 只有部署前后 SO1 会话失败指纹保持一致，且 MySQL、浏览器没有变差时，才允许 `pass_with_warning`
- 验证报告会明确写入 `inherited_so1_session_degradation`
- `/livez`、build-info、Git HEAD、正式交付链路等原有门禁不放宽

最终功能候选：

- `7414ad596aa8d1fb6ecc87d6ae3c81d55ff42746`

新部署目标：

- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
- 第一父提交：当前生产 `7d637b90ac2b177de86bae024713ac9172bb26fa`
- 第二父提交：功能候选 `7414ad596aa8d1fb6ecc87d6ae3c81d55ff42746`
- 部署目标与功能候选文件树完全一致，零文件差异

## CI 与 V3 制品

临时构建 PR：#51，`[DO NOT MERGE]`

提交 `292b43ef439b6102fd34b3c7b198cc7671b65eab` 的结果：

- 标准 tests：success
- LAPI Parser Center CI：success
- V3 不可变离线部署构建：success
- V3 Run：`31022261240`
- V3 Job：`92361708127`
- Artifact：`8937175097`

V3 Job 全部步骤通过：不可变目标测试、Windows PowerShell 5.1、依赖审计、离线打包、哈希与安全标志验证、制品上传。

旧的非 V3 `Build production safe deployment package` 工作流失败不影响本次制品；交付只使用成功的 V3 Artifact。

制品信息：

- 外层 Artifact SHA-256：`701170dcd80fd2fddaeb4e29d1fa11fd1c6563dadc133317b92cba2eba56032a`
- 内层部署 ZIP：`LOLDataSystem-full-bug-repair-safe-deploy-292b43ef439b-py311-py314-winps51-v3.zip`
- 内层部署 ZIP SHA-256：`2d529a11c449f129f6ae511ddd8bd8b5ab145f4fa6654c2dee79ec83aff97981`
- 内层部署 ZIP 大小：`85,815,771` 字节
- Package content SHA-256：`6347a8ec8fce691e169ebed84df682d2197a8d0cc468141de094325ff6c06848`
- 支持 Python：3.11、3.12、3.13、3.14
- Package revision：3
- `baseline_aware_readiness=true`

已完成本地二次复核：

- metadata 与内层 ZIP 哈希、大小一致
- manifest 51 个文件逐一大小和 SHA-256：PASS
- 所有 V3 安全标志：PASS
- 部署脚本包含停服前基线采集与 `BaselineHealthPath`：PASS
- 验证脚本包含 MySQL、浏览器、新 SO1 回归拦截和 inherited SO1 warning：PASS
- `release.bundle` 完整历史验证：PASS
- 当前生产祖先链：PASS
- 当前生产为目标第一父提交：PASS
- 部署目标与功能候选零文件差异：PASS

## 下一步

1. 下载并解压新的 V3 Artifact。
2. 双击内层目录中的 `run-deploy.cmd`。
3. 部署器先在生产不停机时构建候选环境并运行测试，然后保存停服前健康基线、备份、切换、启动和生产验证；任何真实回归仍自动回滚。
4. 部署后提交完整控制台输出、生成的 `verification-report.json`，以及五个 P3B 页面截图。
5. 如果部署前后保持同一个 SO1 会话降级，允许报告状态为 `pass_with_warning`，但必须同时看到 `inherited_so1_session_degradation=true`；这不等于忽略其他 readiness 失败。
6. P3B 实机验收通过前，不合并 PR #41，不关闭 Issue #40。

禁止部署此前失败且没有制品的目标：

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
