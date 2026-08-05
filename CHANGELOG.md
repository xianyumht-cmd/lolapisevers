# Changelog

本文件记录 `lolapisevers` 面向生产使用的重要变更。时间采用中国标准时间（UTC+8）。

## 2026-08-05

### WEBUI-CONTROL-PANEL-003 P0 实机验收修复

- 提交 `5a1f6420867e289a9dc36b6ef62fa116b8b47880` 已在 Windows 生产机安全部署成功，324 项候选测试、Windows 服务、`livez`、`readyz`、build-info、Git HEAD、合集和 ARAM 正式链路全部通过。
- 新 6178 根控制台完成实机视觉验收：固定侧栏、顶栏、面包屑、微软雅黑字体、状态卡、Provider 表格、快捷入口和本地 SVG 图标均正常加载。
- 修复把“蓝奏监控任务降级”误判为“6178 控制台服务异常”的状态语义错误。
- 总览状态改为三档：核心服务与业务均正常为绿色；核心服务正常但存在业务告警为黄色；5001 或 6178 实际不可用才显示红色。
- 修复 `LOL_BAN_4PNG_TOKEN` 已写入 `app_env.local.ps1`、但 5001 重启后可能没有继承该环境变量的问题。
- 新增 Python 启动环境兜底：只解析本地 PowerShell 环境文件中的安全字面量，不执行 PowerShell、不覆盖已有环境变量、不回显 Secret。
- 删除测试生成的 `config/interface-parser-center.json` 和 `data/contact_risk.db`，并加入 `.gitignore` 防线，禁止运行态数据进入源码提交和部署包。
- 提交 `51a93e05fd4bd49e451e864ec7af305961d8a47a` 已在 Windows 生产机安全部署成功：327 项测试、全部 PowerShell 5.1 解析、新控制台/封号页/解析中心 JavaScript 语法检查、Windows 服务、`livez`、`readyz`、build-info、Git HEAD、shard 与 ARAM 正式链路全部通过。
- 第二次生产验证报告状态为 `pass`，备份位于 `D:\project2\lolapisevers.deploy-backups\20260805-101138-full-bug-repair-51a93e05fd4b`。

### 6178 运行时热修复

- 修复 4PNG Token 只保存到 6178、未同步加载到 5001，导致所有封号 Provider 最终统一返回 503 的问题。
- `LOL_BAN_4PNG_TOKEN` 加入 5001 严格热加载白名单；封号页保存 Token 后会立即安全热加载，不再默认要求手工重启。
- 页面同时显示 Secret 的磁盘配置状态和 5001 运行时加载状态，真实 Token 始终不回显。
- 修复接口与解析中心 `renderResponseTree` 缺少右花括号造成的 JavaScript 语法错误；Provider 编辑、页签、Secret、备份和回滚功能恢复可用。
- 新增 `/parser-center/secrets` 与 `/parser-center/advanced` 独立页面路径，左侧菜单不再依赖查询参数模拟跳转。
- Provider 直连与 5001 正式链路拆分为独立测试按钮，并增加 Secret 未加载、配置错误、超时、网络错误、业务拒绝和响应无效等安全诊断分类。
- CI 新增最终渲染页面检查：根控制台、解析中心、Secret 页面和封号页的每段 JavaScript 均执行 `node --check`；页面脚本错误将阻断部署包。

### 6178 专业控制台导航与封号配置完善

- 将 6178 从横向按钮堆叠改为正式控制台结构：固定左侧导航、折叠菜单、移动端菜单和内容工作区。
- 主面板新增并固定展示以下入口：
  - 控制台总览
  - 封号查询
  - 接口与解析中心
  - Secret 与备份
  - 接口调试器
  - 蓝奏配置、监控项、通知目标
  - 主接口配置、日志、诊断、安全与回滚
- `/parser-center` 继续使用真实管理 API，不再作为孤立工程页：支持 Provider 可视化编辑、测试解析、Secret 保存、配置备份和回滚。
- `/query-console/lolban` 新增 4PNG Token 专用安全输入：真实 Token 仅写入本机 Secret，Provider 配置仍保留 `$secret:LOL_BAN_4PNG_TOKEN`。
- 4PNG Token 保存后，本页直连测试立即可用；5001 正式链路通过安全热加载或服务启动环境兜底读取。
- 控制台导航为服务端统一注入，不改变现有配置格式、认证策略、备份策略和查询协议。

### 封号备用 Provider

- 新增 `LOL2099 免费备用接口`：按本机浏览器真实请求捕获结果接入，使用 `POST https://lol2099.top/`、`action=query_lol` 和 `qq` 表单参数。
- 新增 `4PNG 收费备用接口`：使用 `GET https://yun.4png.com/api/query.html`、`qq` 与 Secret Token。
- 两个备用 Provider 均默认关闭，不会自动消耗收费次数。
- 推荐顺序：现有主接口 → LOL2099 → 4PNG。
- 业务码异常、未知状态、次数上限和典型推广提示不会作为成功查询结果发送给用户。

### 实机部署

- 提交 `19edfc9c189f6b269793ed750e42548268fcc115` 已在 Windows 生产机安全部署成功，完成 LOL2099 与 4PNG 备用 Provider 基线。
- 提交 `28e68e75ee14674bba10606587937473d37baa1e` 已在 Windows 生产机安全部署成功，完成 6178 专业控制台、解析中心入口和 4PNG Token 专用配置入口。
- 提交 `5a1f6420867e289a9dc36b6ef62fa116b8b47880` 已在 Windows 生产机安全部署成功，完成独立新总览、统一设计系统、管理令牌 Dialog、Skeleton、Toast 和共享控制台组件。
- 提交 `51a93e05fd4bd49e451e864ec7af305961d8a47a` 已在 Windows 生产机安全部署成功，完成 P0 状态语义和 4PNG Token 启动加载修复。
- 最新生产验证报告状态为 `pass`，备份保存在仓库外部部署备份目录。
- `observability=status=degraded` 表示可选上游或业务任务存在降级，不等同于 5001 或 6178 核心服务故障。

## 2026-08-04

### 封号查询独立管理页 P1

- 新增 `/query-console/lolban` 独立配置与实时诊断页面。
- 同时展示磁盘配置和 5001 当前运行时 Provider。
- 支持 Provider 增删、启停、排序语义、GET/POST、Query、Form、Headers、JSON Body、超时和解析规则。
- 支持 Provider 直连测试与 `/api/v2/lolban` 正式链路并排测试。
- 保存后受控热加载 5001，无需重启整个服务。
- Secret、Authorization、Cookie、Token、API Key 和 URL 内嵌凭据均脱敏；保存 `***` 时保留原值。
- V3 安全部署工作流改为锁定 PR Head 或事件提交，生成不可变离线候选包。

### 接口与解析中心

- 第三方请求、响应解析、命中判定和公开模板统一由 Windows 接口端处理。
- 支持 `$secret:NAME` 引用、响应字段树、路径捕获、测试预览、Schema 校验、原子保存和备份回滚。
- 群内公开结果禁止出现第三方域名、Provider、`by` 和接口来源。

## 2026-07-30

### WebUI 主题与易用性

- 6178 增加日间、夜间和跟随系统三种主题。
- 统一表单、状态卡片、日志、备份回滚和服务管理视觉样式。
- 保留管理令牌、本机访问限制和操作审计。
