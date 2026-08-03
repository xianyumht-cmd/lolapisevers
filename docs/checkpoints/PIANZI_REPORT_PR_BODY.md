## 目标

把已从目标网站正式前端恢复的匿名举报协议接入 LOLDataSystem，同时保留本地先落盘、幂等和失败重试。

## 改动

- 新增受控 multipart 文本表单传输；
- 内部选择头在发送前移除；
- boundary 由 Requests 自动生成，禁止手工 Content-Type；
- 默认配置增加禁用状态的匿名举报 Provider；
- 成功响应 `success=true` 映射为 `pending`；
- 增加真实 multipart 编码、空字段、boundary、错误配置和旧表单兼容测试。

## 安全边界

- 默认 Provider 不自动启用；
- 不修改现有骗子查询 Provider；
- 不在公开输出中显示目标域名或 Provider；
- 本 PR 不直接部署生产，也不发送举报。
