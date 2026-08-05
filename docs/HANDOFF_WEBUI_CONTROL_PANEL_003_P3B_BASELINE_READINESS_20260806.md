# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 交接

更新时间：2026-08-06 01:11 +08:00

## 新对话从这里开始

先读取：

1. `docs/HANDOFF_LATEST.md`
2. 本文档
3. `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`

继续任务时不要重新设计 P3B 页面，也不要部署当前两个失败目标。第一步应修复 V3 构建器的 **Verifier readyz block anchor** 换行标准化问题，重新跑标准 CI，再生成新的生产第一父提交目标和离线一键部署包。

## 当前真实状态

- 仓库：`xianyumht-cmd/lolapisevers`
- Issue：#40，保持打开
- Draft PR：#41，保持 Draft，禁止合并
- 功能分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- 生产仍是 P3A，P3B 尚未部署
- 不要声称任何 P3B 新包已经部署或验收

P3A 已在 Windows 生产机安全部署并通过实机验收：333 项测试、Windows 服务、`/livez`、`/readyz`、build-info、Git HEAD、合集和 ARAM 正式交付链路通过，verification report 为 `pass`。

## P3B 页面功能

P3B 五个页面已经完成分支实现：

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。共享控制台 Shell、配置脚本、Secret 脱敏、Watcher 密码掩码往返、通知 Header 掩码往返、本机回环或 `WEBUI_ADMIN_TOKEN` 管理保护均已实现。

## Windows 实机失败根因

最初 P3B 部署在切换生产前被旧验证规则拦截：当前生产已有 SO1 会话依赖降级，候选没有引入新的降级，但原 V3 验证器把 inherited baseline degradation 误判为候选失败。

已实现的基线感知规则：

- 停止生产前保存 `pre-switch-health.json`
- 部署后重新采集 readiness
- 仅允许 **SO1 会话依赖** 在部署前后保持同样的既有降级
- 新增依赖失败、状态恶化、其他 readiness 失败仍必须回滚
- 不降低 `/livez`、build-info、Git HEAD、正式交付链路等验证要求

## 已完成的代码与测试

最终干净功能候选曾形成：

- `ac5d29d7e52c9cab45765deda489d28a933dd9ce`

之后修复 V3 构建器部署调用锚点 CRLF/LF 不匹配：

- 当前构建器候选：`5df00bb8e0763972294fde9443f26436c42b2320`
- 只修改 V3 构建器和对应回归测试

该候选已经通过：

- Linux 全量测试
- Windows 全量测试
- Parser Center 专项与全套测试
- 341 项测试
- 全部最终 WebUI JavaScript 生成与语法检查
- 17 个 PowerShell 脚本的 Windows PowerShell 5.1 解析
- 依赖安全审计，无已知漏洞

## 两次 V3 构建失败记录

### 第一次失败目标：禁止部署

- 目标：`f9e00b505dc549f3d761348dc741535f4294e352`
- 临时 Draft PR：#49
- V3 Run：`31019102202`
- 不可变 341 项测试、PowerShell 5.1、依赖审计通过
- ZIP 构建失败
- 原因：`Deployment verifier call anchor was not unique.`
- 根因：Windows PowerShell 5.1 here-string 使用 CRLF，而被扫描部署脚本为 LF，导致多行锚点计数为 0
- 未上传制品，不可部署

### 第二次失败目标：禁止部署

- 目标：`954f7748d41da9c3264441d33d60b7c9273fd946`
- 功能候选：`5df00bb8e0763972294fde9443f26436c42b2320`
- 两者零文件差异
- 第一父提交是当前生产 `7d637b90ac2b177de86bae024713ac9172bb26fa`
- 临时 Draft PR：#50，禁止合并
- V3 Run：`31020489861`
- Job：`92355626999`
- 不可变 341 项测试通过
- WebUI JavaScript 通过
- 17 个 PowerShell 脚本的 Windows PowerShell 5.1 解析通过
- 依赖安全审计通过
- ZIP 构建失败
- 精确原因：`Verifier readyz block anchor was not unique.`
- 失败位置：`ops/Build-FullBugRepairPackageV3.ps1` 约第 325 行
- `Verify-FullBugRepairDeployment.ps1` 的 readyz 替换区块仍存在与前一次相同类型的 CRLF/LF 多行锚点问题
- 哈希和安全标志验证、制品上传均被跳过
- 没有可部署 ZIP

## 下一步必须按顺序执行

1. 检查 `ops/Build-FullBugRepairPackageV3.ps1` 中 Verifier readyz block 的查找锚点和替换文本。
2. 与部署调用锚点修复保持一致：将 here-string 锚点和替换文本标准化为 LF 后，再要求精确匹配一次；不要放宽唯一性校验。
3. 增加或更新 `tests/test_v3_baseline_readiness.py`，覆盖 CRLF 构建器输入与 LF 验证脚本内容的真实组合。
4. 在功能分支运行标准 Linux、Windows、Parser Center、341+ 项测试、全部 WebUI JavaScript、PowerShell 5.1 和依赖审计。
5. 全绿后，以当前生产 `7d637b90...` 为第一父提交创建 **新的** 部署目标；不要复用 `f9e00b50...` 或 `954f7748...`。
6. 验证新部署目标与最终功能候选零文件差异。
7. 创建新的 `[DO NOT MERGE]` 临时 Draft PR 触发 V3 构建。
8. 只有 Run 全绿、制品上传成功并完成本地 ZIP/manifest/metadata/hash/安全标志复核后，才向用户交付一键包。
9. 用户在 Windows 生产机运行 `run-deploy.cmd` 后，再依据真实日志、verification report 和页面截图验收 P3B。
10. P3B 实机验收前，不合并 PR #41，不关闭 Issue #40。

## P3B 实机验收重点

部署成功后至少检查：

- 目标 commit、Git HEAD、build-info 一致
- `/livez` 200
- `/readyz`：只允许与部署前完全相同的 inherited SO1 session degradation
- 6178 首页和本地静态资源可加载
- 五个 P3B 页面可访问
- 旧 `?tab=` 地址正确 307 跳转
- 主接口配置读取、保存、备份和重启提示
- 蓝奏配置掩码往返与热刷新
- watcher 新增、编辑、启停、删除、扫描、密码保留
- 通知目标 Header 脱敏、保留与测试推送
- 接口调试器 Path、Query、Header、JSON Body 和结果展示
- 合集与 ARAM 正式交付链路不回归

## 禁止事项

- 不部署 `f9e00b505dc549f3d761348dc741535f4294e352`
- 不部署 `954f7748d41da9c3264441d33d60b7c9273fd946`
- 不合并临时构建 PR #49 或 #50
- 不合并 PR #41
- 不关闭 Issue #40
- 不把构建失败说成功
- 不把候选 CI 通过说成 Windows 生产部署成功
