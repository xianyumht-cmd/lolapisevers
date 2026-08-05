# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 交接

更新时间：2026-08-06 01:20 +08:00

## 当前断点

P3B 基线感知 readiness 修复、标准 CI、V3 不可变离线部署构建和本地制品复核均已完成。当前不再有代码或打包阻塞，下一步是 Windows 生产机部署与实机验收。

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

P3A 已在 Windows 生产机安全部署并通过实机验收：333 项测试、Windows 服务、`/livez`、`/readyz`、build-info、Git HEAD、合集和 ARAM 正式交付链路通过，verification report 为 `pass`。

## P3B 页面功能

P3B 五个页面已完成：

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。共享控制台 Shell、Secret 脱敏、Watcher 密码掩码往返、通知 Header 掩码往返、本机回环或 `WEBUI_ADMIN_TOKEN` 管理保护均已实现。

## Windows 首次部署失败根因

首次 P3B 部署在生产切换验证阶段回滚。诊断包证明：

- 21:07 Keepalive 查询成功
- 21:17 SO1 会话探测已经开始超时
- 21:22 才开始 P3B 部署
- 回滚后的旧生产仍连续 `/readyz` 503
- MySQL 为 up
- Chromium 浏览器为 up
- 只有 `so1_session=false`，失败原因是 TimeoutError
- 群查询正式链路仍持续返回 HTTP 200

因此不是 P3B 页面代码或服务切换引入的新回归，而是旧验证器把部署前已有的 SO1 会话依赖降级误判为候选故障。

## 基线感知规则

当前部署器和验证器已经实现：

- 停止生产前保存 `pre-switch-health.json`
- 部署后重新采集 readiness
- MySQL 不是 up：失败并回滚
- SO1 Chromium 浏览器不是 up：失败并回滚
- 部署前 SO1 会话正常、部署后失效：失败并回滚
- 部署前后 SO1 会话失败指纹不同或状态恶化：失败并回滚
- 只有相同的既有 SO1 会话降级才允许 `pass_with_warning`
- 报告明确写入 `inherited_so1_session_degradation=true`
- `/livez`、build-info、Git HEAD、正式交付链路等门禁保持不变

这不是忽略 `/readyz`，而是区分“候选引入的新回归”和“部署前已存在且部署后没有恶化的依赖降级”。

## 最终代码与部署目标

最终功能候选：

- `7414ad596aa8d1fb6ecc87d6ae3c81d55ff42746`

最终 V3 部署目标：

- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
- 第一父提交：当前生产 `7d637b90ac2b177de86bae024713ac9172bb26fa`
- 第二父提交：功能候选 `7414ad596aa8d1fb6ecc87d6ae3c81d55ff42746`
- 两者文件树：`1bbc7a6907841eafd28b5ebe974dc5a1386bb12c`
- 部署目标与功能候选零文件差异

## CI 与 V3 构建

临时 Draft PR：#51，`[DO NOT MERGE]`

提交 `292b43ef439b6102fd34b3c7b198cc7671b65eab` 已通过：

- 标准 tests：success
- LAPI Parser Center CI：success
- V3 不可变离线部署构建：success
- V3 Run：`31022261240`
- V3 Job：`92361708127`
- Artifact：`8937175097`

V3 Job 的以下步骤全部成功：

- immutable target tests
- Windows PowerShell 5.1 解析
- dependency audit
- V3 immutable offline package build
- hashes and safety flags verification
- artifact upload

旧的非 V3打包工作流失败不作为交付依据；本次只使用成功的 V3 Artifact。

## 制品信息

外层 Artifact：

- 文件名：`LOLDataSystem-WEBUI-P3B-baseline-readiness-v3-20260806.zip`
- SHA-256：`701170dcd80fd2fddaeb4e29d1fa11fd1c6563dadc133317b92cba2eba56032a`

内层部署 ZIP：

- 文件名：`LOLDataSystem-full-bug-repair-safe-deploy-292b43ef439b-py311-py314-winps51-v3.zip`
- SHA-256：`2d529a11c449f129f6ae511ddd8bd8b5ab145f4fa6654c2dee79ec83aff97981`
- 大小：`85,815,771` 字节
- Package content SHA-256：`6347a8ec8fce691e169ebed84df682d2197a8d0cc468141de094325ff6c06848`
- Package revision：3
- 支持 Python：3.11、3.12、3.13、3.14
- `powershell_utf8_parse_input=true`
- `baseline_aware_readiness=true`

## 本地二次复核

已经完成：

- 外层 Artifact SHA-256 与 Actions digest 一致
- metadata 记录的内层 ZIP 名称、哈希、大小一致
- manifest 51 个文件逐一大小和 SHA-256：PASS
- V3 安全标志：PASS
- `Deploy-FullBugRepairSafe.ps1` 包含停服前健康基线采集：PASS
- `Verify-FullBugRepairProduction.ps1` 包含 MySQL、浏览器、SO1 回归门禁和 inherited warning：PASS
- `release.bundle` 完整历史验证：PASS
- 当前生产是部署目标祖先：PASS
- 当前生产是部署目标第一父提交：PASS
- 部署目标与最终功能候选零文件差异：PASS

## 旧失败目标

以下目标均没有可部署制品，继续禁止部署：

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`

对应临时 PR #49、#50 不得合并。

## 下一步必须按顺序执行

1. 下载并解压外层 V3 Artifact。
2. 再解压内层部署 ZIP。
3. 双击 `run-deploy.cmd`。
4. 保留完整控制台输出。
5. 找到并提交部署生成的 `verification-report.json`。
6. 部署成功后按 Ctrl + F5，实机验收五个 P3B 页面。
7. 验证五个旧 `?tab=` 地址是否 307 跳转到新页面。
8. 检查合集与 ARAM 正式交付链路没有回归。
9. 如果报告为 `pass_with_warning`，必须确认唯一降级原因是 `inherited_so1_session_degradation`，且 MySQL、Chromium、服务、Git HEAD、build-info 和正式交付链路全部通过。
10. P3B 实机验收前，不合并 PR #41，不关闭 Issue #40。

## P3B 实机验收重点

- 目标 commit、Git HEAD、build-info 一致
- `/livez` 200
- `/readyz` 不允许新回归
- 五个 P3B 页面可访问
- 旧 `?tab=` 地址正确 307 跳转
- 主接口配置读取、保存、备份和重启提示
- 蓝奏配置环境覆盖状态、掩码往返与热刷新
- watcher 新增、编辑、启停、删除、扫描、密码保留
- 通知目标 Header 脱敏、保留与测试推送
- 接口调试器 Path、Query、Header、JSON Body 和结果展示
- 合集与 ARAM 正式交付链路不回归
