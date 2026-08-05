# Latest handoff

更新时间：2026-08-06 03:25 +08:00

当前任务请按顺序读取：

- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_BASELINE_READINESS_20260806.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3A_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P0_ACCEPTANCE_20260805.md`
- `docs/HANDOFF_WEBUI_CONTROL_PANEL_003.md`
- `docs/PLAN_WEBUI_CONTROL_PANEL_003.md`
- `CHANGELOG.md`

当前主题：继续 `WEBUI-CONTROL-PANEL-003` P3B。首轮 P3B 已成功部署并提交五个页面截图；页面路由和共享 Shell 正常，但截图暴露三个验收缺口。缺口已修复、CI 已通过、新增量 V3 部署包已生成，当前等待 Windows 生产机部署新目标并复验三个页面。

## 当前真实状态

- 当前生产：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- Windows 服务：Running
- 当前生产部署结果：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`
- Issue #40 保持打开
- Draft PR #41 保持 Draft，P3B 操作验收完成前禁止合并

当前生产备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-023757-full-bug-repair-7524a5ea36b5`

## 五个页面截图结论

以下页面均已在生产机正常加载：

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

截图确认：

- 新控制台 Shell、侧栏、面包屑、页面标题和激活态正常
- 主接口配置读取成功
- 蓝奏全局配置读取成功
- 53 个 Watcher 正常加载并显示运行状态
- 通知目标正常加载
- 接口调试器成功加载 69 个 OpenAPI 接口

但首轮截图不能判定 P3B 通过，因为发现：

1. 蓝奏通知模板在 WebUI 中显示 `????`；
2. 通知目标回调 URL 的查询令牌在页面中明文显示；
3. 接口调试器缺少 Header JSON 输入。

用户已确认：机器人实际收到的监控通知没有乱码，乱码是 WebUI 长期存在的显示问题。不得把它解释为机器人发送链路或真实通知模板已经损坏，也不得通过部署擅自改写真实通知内容。

## 已完成的后续修复

### WebUI 历史模板保护

- 检测包含连续 `???` 且仍有 `{title}`、`{url}` 的历史显示异常值
- 页面不再把异常字符串直接显示为可编辑内容
- 显示警告并保持输入框为空
- 用户不输入新模板时，保存请求不携带 `notification_template`
- 因此原有运行模板和机器人通知内容保持不变
- 只有用户明确输入新模板才替换

### 通知目标 URL Secret 脱敏

- `token`、`api_key`、`secret`、`password`、`key` 等敏感查询参数只返回掩码
- `%2A%2A%2A` 掩码保存时恢复原值
- 仅当 scheme、host、path 未改变时允许恢复
- 目标地址改变时禁止把旧 Secret 静默复制到新地址
- Headers 原有 `***` 掩码往返规则保留

### 接口调试器 Header JSON

- 新增“请求 Headers JSON”输入框
- 服务端验证 Header 名、数量和值长度
- 禁止 Host、Content-Length 和 hop-by-hop Header
- 内部自动注入的管理令牌不能被页面覆盖
- 调试结果中的敏感响应 Header 和请求 URL 查询值会脱敏

## 修复候选与 CI

最终运行代码候选：

- `1aa90eb3c9519e4c0cbe8c9a8cd97c9a5e66bdaa`

标准验证：

- tests Run `31038403674`：success
- Linux：success
- Windows：success
- dependency audit：success
- Parser Center Run `31038403744`：success

## 新增量部署目标

目标：

- `dda1c27453eb3b4cf0b79a53ff043369f7662736`
- 第一父提交：当前生产 `7524a5ea36b53a4186a1934edb69b691af56ac09`
- 第二父提交：修复候选 `1aa90eb3c9519e4c0cbe8c9a8cd97c9a5e66bdaa`
- 目标与修复候选 tree：`909fc8e0292559c96ff9cff7b886ca9bed89a5d3`
- 目标与修复候选零文件差异：PASS

V3 构建：

- Run：`31038652544`
- Job：`92417180981`
- Artifact：`8943693600`
- 345 项测试：PASS
- WebUI JavaScript：PASS
- Windows PowerShell 5.1：17 个脚本 PASS
- dependency audit：无已知漏洞
- 临时 Draft PR #56 只用于构建，禁止合并 master

新部署 ZIP：

- `LOLDataSystem-full-bug-repair-safe-deploy-dda1c27453eb-py311-py314-winps51-v3.zip`
- SHA-256：`0f28a8f1bb0135f2feb6aa61f6ec844a5a1696736673895c8b3dcaca49502dca`
- 大小：`85,905,966` 字节
- Package content SHA-256：`40d24b8068f2147d2cbb99b9e10eaaff0ffe70cef944e438d9dcc652b762b8a5`
- Python：3.11、3.12、3.13、3.14
- Package revision：3
- `baseline_aware_readiness=true`

## 当前下一步

1. 只使用目标 `dda1c274...` 的新 ZIP，解压后双击 `run-deploy.cmd`。
2. 提交完整部署窗口输出、`pre-switch-health.json` 和 `verification-report.json`。
3. 部署成功后 Ctrl + F5。
4. 复验 `/lanzou/config`：不再直接显示 `????`；出现保护提示且留空不会覆盖现有模板。
5. 复验 `/lanzou/targets`：回调 URL 中敏感查询值必须显示为掩码。
6. 复验 `/api-debugger`：必须出现 Header JSON，并至少发送一次安全只读请求。
7. 再验收旧 `?tab=` 307 跳转及保存、备份、Watcher、测试推送操作。
8. P3B 完整验收前不合并 PR #41，不关闭 Issue #40。

## 禁止再次部署的旧目标

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`

目标 `7524a5ea...` 是当前稳定生产，不需要回滚；但它不包含本轮三个页面验收修复，不再作为后续验收部署包使用。
