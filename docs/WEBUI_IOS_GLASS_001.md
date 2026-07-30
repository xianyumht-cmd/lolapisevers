# WEBUI-IOS-001：接口控制台 iOS 玻璃主题与易用性改造

- 仓库：`xianyumht-cmd/lolapisevers`
- 实现分支：`codex/webui-ios-glass-20260730`
- 合并提交：`066154ce1737b38de07fa20eb9553ba804a6ee8f`
- 状态：**COMPLETED**
- 开始时间：2026-07-30
- 完成时间：2026-07-30
- 目标：让接口端 WebUI 保持现有完整配置能力，同时通过更清楚的日常入口完成配置，并统一为可切换白天、夜间和跟随系统的 iOS 玻璃风格。

## 1. 链路审查结论

### 页面生成链

`lanzou_update_push_api_server/server.py`
→ `render_runtime_dashboard()`
→ `lanzou_update_push_api_server/ui_runtime.py`
→ `render_control_dashboard()`
→ `lanzou_update_push_api_server/ui_control.py`

`ui_runtime.py` 会在基础页面上追加管理令牌、系统与安全、备份回滚、服务重启和交互脚本。因此主题最终接在 `server.py` 的页面响应边界，确保所有运行时扩展完成后再统一套用主题。

### 配置读写链

- 主接口配置：`/admin/main-config` → `config_facade.py` → `management.py` → `ops/app_env.local.ps1`
- 蓝奏配置：`/admin/lanzou-config` → `management.py` → 配置文件并热刷新运行时
- 监控项与通知目标：页面表格 CRUD → 蓝奏配置保存接口
- 管理令牌：浏览器会话存储 → `x-admin-token` → `security.py`
- 备份、回滚、审计、服务重启：`control_extensions.py`

接口端原本已经能通过表单完成绝大多数常用配置。本任务只升级展示和操作体验，不改变配置文件格式、令牌校验、保存语义或服务重启语义。

## 2. 已完成实现

### 统一主题基础设施

- 新增独立主题模块 `ui_theme.py`。
- 使用 CSS 变量实现半透明玻璃面板、背景光晕、圆角、柔和阴影和高亮边缘。
- 支持 `light`、`dark`、`system` 三种模式。
- 主题保存到浏览器 `localStorage`，刷新和重新打开页面后保持。
- 跟随系统模式时监听系统主题变化。
- 不使用第三方 CDN、字体或外部脚本。
- 不支持 `backdrop-filter` 的浏览器自动退化为较不透明面板。

### 日常操作体验

- 顶部自动加入日间、跟随、夜间主题切换控件。
- 统一主操作、危险操作和次要操作的视觉层级。
- 优化表单、开关、表格、日志、状态卡片、Toast 和移动端布局。
- 保留全部标签页、管理令牌、安全控制、备份回滚和服务管理功能。

### 验证链

- 新增主题契约测试，覆盖三模式、存储键、系统模式监听、移动端和幂等注入。
- WebUI JavaScript 提取器升级为支持多个独立脚本块。
- Python 全量测试通过。
- 生成 WebUI JavaScript 与 `node --check` 通过。

## 3. 最终进度

- [x] AUDIT：页面、配置、权限和保存链路审查
- [x] PLAN：范围、兼容和验收标准确定
- [x] IMPLEMENT：主题模块与最终页面注入
- [x] VERIFY：单元测试和 WebUI 语法验证
- [x] COMPLETE：合并并标记完成

## 4. 完成结果

1. 白天、夜间、跟随系统三种模式可直接切换。
2. 主题在刷新和重新打开页面后保持。
3. 所有接口端标签页仍可读取和保存原配置。
4. 管理令牌、安全保护、备份回滚和服务管理保持有效。
5. 全量 CI 通过并已合并到 `master`。
