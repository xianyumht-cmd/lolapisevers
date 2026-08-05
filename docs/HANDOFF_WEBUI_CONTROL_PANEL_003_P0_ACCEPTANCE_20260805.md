# WEBUI-CONTROL-PANEL-003 P0 实机验收与修复交接

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 首次生产预览提交：`5a1f6420867e289a9dc36b6ef62fa116b8b47880`
- 当前生产提交：`51a93e05fd4bd49e451e864ec7af305961d8a47a`
- Provider Secret 就地配置候选：`420bd967ac50543b6d34b5049d90363d9591f593`
- 日期：2026-08-05

## 1. 已完成的生产部署

### 1.1 首次 P0 预览

提交 `5a1f6420867e289a9dc36b6ef62fa116b8b47880` 已在 Windows 生产机安全部署：

- 324 项候选测试通过；
- Windows 服务、`/livez`、`/readyz` 正常；
- build-info 与 Git HEAD 匹配；
- shard 与 ARAM 正式链路通过；
- verification report 为 `pass`。

### 1.2 P0 状态与运行时 Secret 修复

提交 `51a93e05fd4bd49e451e864ec7af305961d8a47a` 已在 Windows 生产机安全部署：

- Python 3.14 离线候选环境；
- 327 项测试通过；
- 全部 PowerShell 5.1 解析通过；
- 新控制台、封号页与解析中心 JavaScript 语法检查通过；
- Windows 服务状态 `Running`；
- `/livez`、`/readyz` HTTP 200；
- build-info 与 Git HEAD 匹配；
- shard 与 ARAM 正式交付链路均为 `kind=segments`；
- verification report 为 `pass`；
- 没有触发回滚。

生产备份：

`D:\project2\lolapisevers.deploy-backups\20260805-101138-full-bug-repair-51a93e05fd4b`

验证报告：

`D:\project2\lolapisevers.deploy-backups\20260805-101138-full-bug-repair-51a93e05fd4b\verification-report.json`

## 2. 新控制台视觉验收

6178 根控制台的结构与视觉方向达到 P0 目标：

- 固定深色侧栏；
- 白色顶栏和面包屑；
- 微软雅黑中文字体；
- 状态卡、Provider 表格、快捷入口与告警面板；
- 本地 SVG 图标；
- 不再使用旧毛玻璃根页面；
- 信息密度和层级明显优于旧版控制台。

状态语义已经拆分：

- 6178 控制台可访问由控制面和 `/build-info` 判断；
- Windows 托管服务读取 `state/status`；
- 蓝奏 watcher 降级单独显示为黄色业务告警；
- 只有 5001 或 6178 实际不可用才显示红色服务异常。

## 3. 实机发现的 Provider Secret 问题

当前生产页面进一步暴露两个问题。

### 3.1 主接口 Token 没有专用配置入口

主 Provider `lolban-primary` 的 Query JSON 引用：

`$secret:LOLMAP_API_TOKEN`

但旧页面只为 4PNG 提供安全输入，因此主接口测试会返回：

`Secret 未配置：LOLMAP_API_TOKEN`

正式链路最终会表现为“服务器繁忙”，但根因不是服务器负载，而是主 Provider 的 Secret 缺失。

### 3.2 4PNG Token 信息层级错误

旧设计把一个备用 Provider 的 Token 做成页面级大型标题面板，位于缓存配置和 Provider 列表之前。该控件应归属 `lolban-4png` Provider，而不是整个封号查询页面。

## 4. Provider Secret 就地配置修复

候选提交：

`420bd967ac50543b6d34b5049d90363d9591f593`

### 4.1 页面结构

- 删除页面顶部大型 4PNG Token 面板；
- `lolban-primary` Provider 卡片内显示紧凑的“主接口 Token”；
- `lolban-4png` Provider 卡片内显示紧凑的“4PNG Token”；
- `lolban-lol2099` 不需要 Token，因此不显示 Secret 控件；
- Token 输入位于对应 Provider 的 API URL 附近；
- 每项显示：未配置、磁盘已配置但 5001 未加载、已配置并加载。

### 4.2 安全保存与运行态

- 新增通用端点 `/admin/query-console/lolban/provider-secret`；
- 只允许预定义的 Provider ID 与 Secret 名称映射；
- `lolban-primary` 仅允许写入 `LOLMAP_API_TOKEN`；
- `lolban-4png` 仅允许写入 `LOL_BAN_4PNG_TOKEN`；
- 两个 Secret 都加入 5001 严格热加载白名单；
- 真实 Token 不返回浏览器、不写入 Provider JSON、不进入 URL、日志或诊断输出；
- 保留旧 4PNG 保存端点作为兼容包装，但新页面不再使用它。

### 4.3 测试与清理

安全补丁门已完成：

- 328 项 Linux 测试仅在旧的静态 HTML 断言上发现两处测试设计错误；
- 修正为验证 Provider 卡片就地控件、通用安全端点和旧大型面板不存在；
- 正式提交仅包含 3 个源码文件与 2 个测试文件；
- 一次性补丁脚本与工作流已删除；
- 未提交配置 JSON、SQLite、日志或诊断生成物。

## 5. 当前状态与下一步

当前生产仍运行 `51a93e05fd4bd49e451e864ec7af305961d8a47a`，尚未包含 Provider Secret 就地配置。

下一步：

1. 等待候选分支最终 Linux、Windows、Parser Center、WebUI JavaScript、PowerShell 5.1 和依赖审计全部通过；
2. 生成新的 V3 不可变离线部署包；
3. 在 Windows 生产机部署；
4. 确认页面顶部不再出现大型 4PNG Token 面板；
5. 在主接口卡片内保存 `LOLMAP_API_TOKEN`；
6. 在 4PNG 卡片内检查或更新 `LOL_BAN_4PNG_TOKEN`；
7. 分别测试主接口、LOL2099、4PNG Provider 直连；
8. 测试 `/api/v2/lolban` 正式降级链路；
9. 验收完成前 PR #41 保持 Draft，Issue #40 保持打开。
