# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 与页面验收交接

更新时间：2026-08-06 03:25 +08:00

## 当前断点

P3B 首轮 V3 已在 Windows 生产机完整 `pass`，五个新页面也已提交实机截图。截图确认路由和共享控制台正常，但暴露三个页面验收缺口。缺口已完成修复、标准 CI 和 V3 打包；当前等待部署增量目标 `dda1c274...` 后复验。

继续任务时先读取：

1. `docs/HANDOFF_LATEST.md`
2. 本文档
3. `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`

## 当前生产

- 仓库：`xianyumht-cmd/lolapisevers`
- Issue：#40，保持打开
- Draft PR：#41，保持 Draft
- 功能分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- 服务：`LOLDataSystem`
- 当前生产验证：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`

备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-023757-full-bug-repair-7524a5ea36b5`

## 首轮部署记录

部署目标：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`

结果：

- release.bundle：PASS
- Python 3.14 离线依赖：PASS
- 343 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线：PASS
- 服务切换与启动：PASS
- 后置生产验证：`pass`
- 自动回滚：未触发
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated
- `/readyz`：HTTP 200
- build-info 与 Git HEAD：目标提交
- shard 与 ARAM：`kind=segments`

SO1 基线感知规则已在实机部署中保留，但本次会话已认证，因此没有使用 `pass_with_warning` 路径。

## 五个页面截图验收

截图已覆盖：

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

通过项：

- 五个新 URL 均正常打开
- 统一侧栏、顶部状态、面包屑与激活态正常
- 主接口配置读取正常
- 蓝奏全局配置读取正常
- 53 个 Watcher 正常加载
- 通知目标正常加载
- 调试器加载 69 个接口

未通过项：

1. `/lanzou/config` 的通知模板显示为连续问号；
2. `/lanzou/targets` 的回调 URL 明文显示敏感查询令牌；
3. `/api-debugger` 没有 Header JSON 输入。

用户明确说明：机器人实际收到的蓝奏监控通知没有乱码，乱码一直只存在于 WebUI。因此该问题属于历史 WebUI 显示缺陷，不是发送链路故障，也不是确认过的真实模板数据损坏。修复不得主动改写现有通知模板。

## 页面验收修复

### 1. 历史模板显示保护

- 识别连续 `???` 且包含 `{title}`、`{url}` 的历史异常显示值
- 不把异常值直接填入 textarea
- 显示保护提示
- 未输入新模板时不提交 `notification_template`
- 现有运行模板和机器人实际通知保持原样
- 用户明确输入时才执行替换

### 2. URL 查询 Secret 脱敏与安全往返

- 敏感参数名及 `_token`、`_secret`、`_password`、`_key` 后缀均掩码
- WebUI 返回 `%2A%2A%2A`
- 后端解析后识别为 `***` 并恢复旧值
- 仅 scheme、host、path 相同才允许恢复
- 目标地址改变时要求明确填写新 Secret
- Header `***` 掩码保留原有安全往返

### 3. 调试器 Header JSON

- 前端新增 Header JSON 编辑区
- `/admin/invoke` 接收并验证 Header
- 限制 Header 数量和值长度
- 禁止 Host、Content-Length、Connection 等 hop-by-hop Header
- 内部自动注入令牌优先，不能被 WebUI 覆盖
- 响应 Header 和 request URL 中的敏感值脱敏

## 修复提交与验证

最终运行候选：

- `1aa90eb3c9519e4c0cbe8c9a8cd97c9a5e66bdaa`

标准 CI：

- tests Run `31038403674`：success
- Linux：success
- Windows：success
- dependency audit：success
- Parser Center Run `31038403744`：success

修复新增回归覆盖：

- 自定义 Header 转发
- 敏感响应 Header 脱敏
- 请求 URL 查询 Secret 脱敏
- Host/hop-by-hop Header 拒绝
- 通知目标 URL 掩码
- `%2A%2A%2A` 往返恢复真实 Secret
- 历史模板保护和调试器 Header UI 标记

临时补丁工作流与临时 CI 修改已清理，标准 `.github/workflows/tests.yml` 已恢复。

## 新 V3 增量目标

- 目标：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- 第一父提交：当前生产 `7524a5ea36b53a4186a1934edb69b691af56ac09`
- 第二父提交：最终运行候选 `1aa90eb3c9519e4c0cbe8c9a8cd97c9a5e66bdaa`
- 目标 tree：`909fc8e0292559c96ff9cff7b886ca9bed89a5d3`
- 候选 tree：`909fc8e0292559c96ff9cff7b886ca9bed89a5d3`
- 零文件差异：PASS

构建记录：

- 构造 PR #55 已合并到临时 build 分支，不涉及 master
- V3 Draft PR #56 只用于构建，禁止合并
- V3 Run：`31038652544`
- V3 Job：`92417180981`
- Artifact：`8943693600`
- 345 项测试：PASS
- WebUI JavaScript：PASS
- Windows PowerShell 5.1：17 个脚本 PASS
- pip audit：无已知漏洞

制品：

- 文件：`LOLDataSystem-full-bug-repair-safe-deploy-dda1c27453eb-py311-py314-winps51-v3.zip`
- SHA-256：`0f28a8f1bb0135f2feb6aa61f6ec844a5a1696736673895c8b3dcaca49502dca`
- 大小：`85,905,966` 字节
- Package content SHA-256：`40d24b8068f2147d2cbb99b9e10eaaff0ffe70cef944e438d9dcc652b762b8a5`
- Package revision：3
- Python：3.11、3.12、3.13、3.14
- `powershell_utf8_parse_input=true`
- `baseline_aware_readiness=true`

制品复核：

- 外层 Artifact digest 与 Actions：PASS
- metadata 与内层 ZIP SHA/大小：PASS
- manifest 51 个文件大小和 SHA：PASS
- Package content SHA：PASS
- release.bundle 完整历史：PASS
- 当前生产是目标第一父提交：PASS
- 目标与候选零差异：PASS
- baseline readiness 与自动回滚标记：PASS

## 下一步验收

1. 解压新目标 `dda1c274...` 的 ZIP。
2. 双击 `run-deploy.cmd`。
3. 提交完整控制台输出、`pre-switch-health.json`、`verification-report.json`。
4. 部署成功后 Ctrl + F5。
5. `/lanzou/config`：确认不再直接显示问号模板；保护提示存在；留空保存不得改写实际通知。
6. `/lanzou/targets`：确认 URL 查询令牌只显示掩码；Header 仍显示 `***`。
7. `/api-debugger`：确认 Header JSON 存在，并用只读接口发起一次请求。
8. 验收五个旧 `?tab=` 地址的 307 跳转。
9. 验收主接口保存与备份、Watcher 密码保留、通知目标保存与测试推送。
10. P3B 全部通过后再进入旧 `ui_control.py`、`ui_runtime.py`、旧导航注入和 `/legacy-ui` 退休审查。
11. 整体迁移完成前不合并 PR #41，不关闭 Issue #40。

## 禁止再次部署

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`

当前 `7524a5ea...` 是稳定生产，但不包含本轮三个验收修复；后续只使用目标 `dda1c274...` 的新 V3 包。
