# PIANZI-REPORT-001

## 最终状态

**状态：已完成并通过生产实机验收**

完成时间：2026-08-04 04:28 +08:00

GroupGuard 到 LOLDataSystem 的举报写入鉴权、LOLDataSystem 本地持久化，以及 LOLDataSystem 到 `pianzi.lol` 的匿名举报提交链路均已完成接入并通过 QQ 群实机验收。

最终生产提交：

- `a10e19db060780b829e9d738017a0fdce9dc25c8`

生产回滚备份：

- `D:\project2\lolapisevers.deploy-backups\20260804-041937-pianzi-report-integration`

## 现场问题与根因

最初状态中，GroupGuard 已能把“举报骗子”请求写入 LOLDataSystem，本地 `contact_risk.db` 也能保存并供“查骗子”读取，但生产 `scammer_report` Provider 为空，因此举报没有调用目标网站，只存在本地。

2026-08-04 的只读抓取从目标网站正式前端脚本恢复出匿名举报协议：

- `POST https://pianzi.lol/api/anonymous/report`
- 请求体为浏览器 `FormData`，即 `multipart/form-data`
- 必填字段：`scammer_qq`、`report_content`
- 匿名模式字段：`report_identity_mode=anonymous`
- 成功响应：JSON `success=true`
- 成功代表进入审核，应映射为 `pending`，不能映射为审核通过

## 已实施内容

- 为解析中心增加受控 multipart 文本表单传输。
- 使用内部选择头 `X-LAPI-Request-Encoding: multipart`；该头在发出请求前移除。
- multipart 的 `Content-Type` 和 boundary 只允许 Requests 自动生成，禁止手工写死。
- 默认配置加入 `pianzi-lol-anonymous-report` Provider，并在生产配置中启用。
- 保持本地先落盘、`request_id` 幂等、失败重试队列和公开输出隐藏 Provider 的规则不变。
- 不修改现有“查骗子”查询链路。

## 代码与发布记录

- 实现 PR：`#36`
- 合并提交：`a10e19db060780b829e9d738017a0fdce9dc25c8`
- 生产部署时间：`2026-08-04 04:19:37 +08:00`
- 部署方式：离线 Git bundle + 候选工作树预检 + 精确提交切换
- 候选专项测试：12 项全部通过
- 生产运行时源码清单：79 个文件
- 源码清单 SHA-256：`24daf278cd6db64d292d844c58f0369f865d280dcb3af607e487ec1190da1890`

## 生产验收结果

部署器验证通过：

- 目标提交匹配。
- `pianzi-lol-anonymous-report` Provider 已启用。
- `scammer_report` Provider 数量为 1。
- multipart boundary 由 Requests 正常生成。
- 部署过程未发送外部举报。
- LOLDataSystem 重启及健康检查通过。

QQ 群实机验收由用户确认通过：

- “举报骗子”能够提交到目标网站并进入待审核流程。
- “查骗子”原有查询功能正常。
- 不再出现仅本地保存、未调用上游的旧行为。

## 保留的安全机制

1. 本地记录先落盘，再尝试联网提交。
2. 同一 `request_id` 不重复计数、不重复提交。
3. 上游失败进入持久化重试队列。
4. 上游 `success=true` 映射为 `pending` / 等待审核。
5. 群内公开回复不泄露 Provider、目标域名或内部接口信息。
6. 独立回滚入口与生产备份保留。

## 后续状态

本任务无需继续开发，标记为完成。后续只有在目标网站协议变化、上游提交失败或审核回执格式变化时，才重新开启兼容性诊断任务。
