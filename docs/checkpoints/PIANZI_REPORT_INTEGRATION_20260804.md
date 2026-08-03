# PIANZI-REPORT-001

## 现场结论

GroupGuard 到 LOLDataSystem 的举报写入鉴权已修复，但生产 `scammer_report` Provider 为空，因此举报仅进入本地 `contact_risk.db`，未调用目标网站。

2026-08-04 的只读抓取从目标网站正式前端脚本恢复出匿名举报协议：

- `POST https://pianzi.lol/api/anonymous/report`
- 请求体为浏览器 `FormData`，即 `multipart/form-data`
- 必填字段：`scammer_qq`、`report_content`
- 匿名模式字段：`report_identity_mode=anonymous`
- 成功响应：JSON `success=true`
- 成功代表进入审核，应映射为 `pending`，不能映射为审核通过

## 实施内容

- 为解析中心增加受控 multipart 文本表单传输。
- 使用内部选择头 `X-LAPI-Request-Encoding: multipart`；该头在发出请求前移除。
- multipart 的 `Content-Type` 和 boundary 只允许 Requests 自动生成，禁止手工写死。
- 默认配置加入禁用状态的 `pianzi-lol-anonymous-report` Provider。
- 保持本地先落盘、request_id 幂等、失败重试队列和公开输出隐藏 Provider 的规则不变。

## 生产门禁

代码合并和测试通过后，部署器必须：

1. 备份生产代码、解析中心配置和数据库。
2. 部署 multipart 运行支持。
3. 在生产 `interface-parser-center.json` 中只新增或更新目标 Provider，不覆盖现有查询 Provider。
4. 启用目标 Provider。
5. 重启 `LOLDataSystem` 并验证 `/livez`。
6. 用缺少必填字段的无害请求验证目标接口可达和 multipart 协议，但不得创建举报。
7. 实机举报只能使用经过确认的测试 QQ；成功回复必须为“等待处理”并包含审核回执。
8. 任一步失败自动恢复旧代码和旧配置。
