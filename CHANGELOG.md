# Changelog

本文件记录 `lolapisevers` 面向生产使用的重要变更。时间采用中国标准时间（UTC+8）。

## 2026-08-05

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
- 4PNG Token 保存后，本页直连测试立即可用；5001 正式链路需重启 `LOLDataSystem` 后加载。
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
- 最新部署在停服前完成 308 项候选测试；Windows 服务、`livez`、`readyz`、build-info、Git HEAD、合集和 ARAM 正式交付链路全部通过。
- 最新验证报告状态为 `pass`，生产备份保存在 `D:\project2\lolapisevers.deploy-backups\20260805-012835-full-bug-repair-28e68e75ee14`。
- `observability=status=degraded` 表示某个可选上游处于降级状态，不影响本次控制台发布成功。

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
