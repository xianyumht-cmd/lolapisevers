# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 与页面验收交接

更新时间：2026-08-06 03:44 +08:00

## 当前断点

P3B 的三个首轮页面缺口修复目标已经在 Windows 生产机完成安全部署，验证报告为完整 `pass`，三张复验截图也确认显示层修复生效。当前不再需要继续修改这三个页面，下一步是完成旧地址跳转和实际操作验收。

继续任务时先读取：

1. `docs/HANDOFF_LATEST.md`
2. 本文档
3. `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`

## 当前生产

- 仓库：`xianyumht-cmd/lolapisevers`
- Issue：#40，保持打开
- Draft PR：#41，保持 Draft
- 功能分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- 服务：`LOLDataSystem`
- 生产验证：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`

备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-033214-full-bug-repair-dda1c27453eb`

验证报告：

- `D:\project2\lolapisevers.deploy-backups\20260806-033214-full-bug-repair-dda1c27453eb\verification-report.json`

## 最新部署记录

部署目标：

- `dda1c27453eb3b4cf0b79a53ff043369f7662736`

停服前生产：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`
- `ready=true`
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated

部署过程：

- release.bundle 验证：PASS
- Python 3.14 离线依赖安装：PASS
- 无破损依赖：PASS
- 345 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线采集：PASS
- 生产源码切换：PASS
- build-info 写入：PASS
- 服务启动：PASS
- 后置验证：PASS
- 自动回滚：未触发

生产检查：

- Windows 服务：Running
- `/livez`：HTTP 200
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated
- `/readyz`：HTTP 200
- build-info：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- Git HEAD：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- shard：`kind=segments`
- ARAM：`kind=segments`
- observability 门禁：pass，业务摘要仍为 `status=degraded`

本次生产依赖完整健康，因此没有使用 inherited SO1 degradation 例外。

## 三个首轮缺口复验

### 蓝奏通知模板

用户已明确确认：机器人实际收到的监控通知没有乱码，乱码一直只存在于 WebUI。最新截图显示：

- 连续问号不再作为可编辑模板显示
- 页面出现历史 WebUI 编码损坏保护提示
- 模板输入框为空
- 提示只有输入新内容才替换

这符合“不修改真实通知模板、不影响机器人实际通知”的修复边界。显示层验收通过。

### 通知目标 Secret

最新截图显示：

- 回调地址敏感查询值为 `%2A%2A%2A`
- Header JSON 中 `x-groupguard-token` 为 `***`
- 页面没有暴露真实 Secret

显示层脱敏验收通过。实际保存后的掩码往返仍需操作验收。

### 接口调试器 Header

最新截图显示：

- 已新增“请求 Headers JSON”输入区
- 默认内容为 `{}`
- 69 个 OpenAPI 接口仍正常加载
- Query/Path、超时、服务、响应区布局正常

显示层验收通过。Header 转发和只读请求仍需操作验收。

## 已实现的安全规则

### 历史模板保护

- 识别连续问号且包含 `{title}`、`{url}` 的历史异常显示值
- 不把异常值直接填入 textarea
- 留空保存不携带 `notification_template`
- 只有用户明确输入新内容才替换

### URL 查询 Secret

- 敏感参数只返回掩码
- `%2A%2A%2A` 保存时解析为 `***` 并恢复原值
- 仅 scheme、host、path 未改变时允许恢复
- 目标地址改变时禁止静默复用旧 Secret
- Header `***` 往返规则保留

### 调试器 Header

- 接收并验证自定义 Header JSON
- 限制 Header 数量和值长度
- 拒绝 Host、Content-Length 和 hop-by-hop Header
- 内部管理令牌不能被页面覆盖
- 请求 URL 与响应 Header 中的敏感信息会脱敏

## 剩余 P3B 操作验收

1. 五个旧 `?tab=` 地址必须 307 跳转到对应新页面。
2. 主接口配置执行一次无害保存，确认备份和重启提示。
3. 蓝奏全局配置保持模板为空执行保存，确认真实模板和机器人通知不变。
4. Watcher 未修改密码执行保存，确认原密码保留。
5. 通知目标未修改 URL/Header Secret 执行保存，确认原 Secret 保留。
6. 执行一次测试推送，确认机器人收到正常中文通知。
7. 接口调试器选择安全只读接口，验证 Query、Header JSON 和响应展示。
8. 全部通过后才标记 P3B 完成。
9. P3B 完成后进入 `ui_control.py`、`ui_runtime.py`、旧导航注入和 `/legacy-ui` 退休审查。
10. 整体迁移完成前不合并 PR #41，不关闭 Issue #40。

## 构建与制品记录

- 运行候选：`1aa90eb3c9519e4c0cbe8c9a8cd97c9a5e66bdaa`
- 部署目标：`dda1c27453eb3b4cf0b79a53ff043369f7662736`
- tests Run：`31038403674`
- Parser Center Run：`31038403744`
- V3 Run：`31038652544`
- V3 Job：`92417180981`
- Artifact：`8943693600`
- ZIP：`LOLDataSystem-full-bug-repair-safe-deploy-dda1c27453eb-py311-py314-winps51-v3.zip`
- ZIP SHA-256：`0f28a8f1bb0135f2feb6aa61f6ec844a5a1696736673895c8b3dcaca49502dca`
- Package content SHA-256：`40d24b8068f2147d2cbb99b9e10eaaff0ffe70cef944e438d9dcc652b762b8a5`

## 禁止再次部署

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
- `7524a5ea36b53a4186a1934edb69b691af56ac09` 不包含最新页面修复，不再作为验收目标
