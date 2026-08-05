# WEBUI-CONTROL-PANEL-003 P0 实机验收与修复交接

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 首次生产预览提交：`5a1f6420867e289a9dc36b6ef62fa116b8b47880`
- 当前生产提交：`51a93e05fd4bd49e451e864ec7af305961d8a47a`
- 日期：2026-08-05

## 1. 首次生产部署结果

P0 首个 V3 包已在 Windows 生产机成功部署到 `5a1f6420867e289a9dc36b6ef62fa116b8b47880`。

部署证据：

- 候选环境安装与依赖检查成功；
- 324 项测试全部通过；
- 生产服务切换成功；
- `/livez` HTTP 200；
- `/readyz` HTTP 200；
- `/build-info` 与 Git HEAD 均匹配目标提交；
- shard 与 ARAM 正式交付链路通过；
- verification report 状态为 `pass`；
- 生产备份位于仓库外部部署备份目录。

## 2. 首次页面验收结论

新 6178 根控制台的结构和视觉方向达到 P0 目标：

- 固定深色侧栏；
- 白色顶栏与面包屑；
- 微软雅黑中文字体；
- 状态卡、Provider 表格、快捷入口和告警面板；
- 本地 SVG 图标；
- 不再使用旧毛玻璃根页面；
- 信息密度和层级明显优于旧版控制台。

首次截图同时暴露两项真实问题：

1. 蓝奏监控任务 `degraded` 被误标为 6178 控制台服务异常；
2. 4PNG Token 已安全写入磁盘，但 5001 重启后可能没有继承该环境变量。

## 3. 已完成修复

### 3.1 状态语义修复

总览现在分开判断：

- 6178 控制台是否可访问：以 `/build-info` 和控制面响应为准；
- Windows 托管服务状态：读取服务状态对象的 `state/status`；
- 蓝奏监控业务降级：单独显示为“蓝奏监控任务存在降级”。

全局状态改为三档：

- 绿色：核心服务正常且没有告警；
- 黄色：核心服务正常，但存在业务告警；
- 红色：5001 或 6178 核心服务实际异常。

### 3.2 Python 启动环境兜底

新增 `core/local_env.py`：

- 在导入封号路由和服务前读取 `ops/app_env.local.ps1`；
- 只解析字面量 `$env:KEY = VALUE`；
- 不执行 PowerShell；
- 忽略表达式和不安全语句；
- 不覆盖已经存在的环境变量；
- 不记录或返回 Secret 值。

这使 `LOL_BAN_4PNG_TOKEN` 在 NSSM/PowerShell 环境继承不完整时仍能由 Python 安全加载。

### 3.3 生成物防线

全量测试曾生成：

- `config/interface-parser-center.json`；
- `data/contact_risk.db`。

两项均已从候选树删除，并加入 `.gitignore`。三套生成的 JavaScript 检查文件也已忽略，防止测试产物进入后续提交和部署包。

## 4. 修复候选验证

最终候选已通过：

- Linux 全量测试；
- Windows 全量测试；
- 327 项测试；
- Parser Center 专项及全套测试；
- 新控制台、封号页、解析中心 JavaScript 语法检查；
- 全部 PowerShell 5.1 解析；
- 依赖安全审计；
- 环境加载器不覆盖已有变量测试；
- 环境加载器拒绝执行 PowerShell 表达式测试；
- 应用启动顺序测试；
- 状态语义回归测试；
- V3 不可变目标测试、manifest 与逐文件哈希验证。

## 5. 第二次生产部署结果

V3 修复包已于 2026-08-05 在 Windows 生产机部署成功。

生产提交：

`51a93e05fd4bd49e451e864ec7af305961d8a47a`

部署证据：

- 使用 Python 3.14 离线候选环境；
- 327 项测试全部通过；
- 全部 PowerShell 5.1 解析通过；
- 新控制台、封号页与解析中心 JavaScript 语法检查通过；
- 生产服务切换成功；
- Windows 服务状态 `Running`；
- `/livez` HTTP 200；
- `/readyz` HTTP 200；
- `/build-info` 与 Git HEAD 均匹配目标提交；
- shard 正式交付链路 `kind=segments`；
- ARAM 正式交付链路 `kind=segments`；
- verification report 状态为 `pass`；
- 没有触发回滚。

生产备份：

`D:\project2\lolapisevers.deploy-backups\20260805-101138-full-bug-repair-51a93e05fd4b`

验证报告：

`D:\project2\lolapisevers.deploy-backups\20260805-101138-full-bug-repair-51a93e05fd4b\verification-report.json`

`observability=status=degraded` 仅表示某个可选业务上游或 watcher 仍处于降级状态，不代表 5001 或 6178 核心服务部署失败。

## 6. 当前状态与下一步

当前生产已运行 `51a93e05fd4bd49e451e864ec7af305961d8a47a`。

部署层验收已经通过。P0 最后只剩页面与 4PNG 运行态验收：

1. 浏览器对 6178 执行 `Ctrl + F5`；
2. 确认 6178 状态卡显示“运行正常”；
3. 若蓝奏 watcher 有问题，只显示黄色业务告警，不再显示红色 6178 服务异常；
4. 确认 4PNG Token 的磁盘状态和 5001 运行态均为已配置；
5. 执行 4PNG Provider 直连测试；
6. 执行 `/api/v2/lolban` 正式链路测试；
7. 页面与 4PNG 验收完成前 PR #41 保持 Draft，Issue #40 保持打开。
