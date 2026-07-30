# WEBUI-IOS-001：接口控制台 iOS 玻璃主题与易用性改造

- 仓库：`xianyumht-cmd/lolapisevers`
- 分支：`codex/webui-ios-glass-20260730`
- 状态：**IMPLEMENTING**
- 开始时间：2026-07-30
- 目标：让接口端 WebUI 保持现有完整配置能力，同时通过更清楚的日常入口完成配置，并统一为可切换白天/夜间的 iOS 玻璃风格。

## 1. 当前链路审查

### 页面生成链

`lanzou_update_push_api_server/server.py`
→ `render_runtime_dashboard()`
→ `lanzou_update_push_api_server/ui_runtime.py`
→ `render_control_dashboard()`
→ `lanzou_update_push_api_server/ui_control.py`

`ui_runtime.py` 会在基础页面上追加管理令牌、系统与安全、备份回滚、服务重启和交互脚本，因此主题必须在运行时最终页面统一注入，不能只修改基础 HTML。

### 配置读写链

- 主接口配置：`/admin/main-config` → `config_facade.py` → `management.py` → `ops/app_env.local.ps1`
- 蓝奏配置：`/admin/lanzou-config` → `management.py` → 配置文件并热刷新运行时
- 监控项与通知目标：页面表格 CRUD → 蓝奏配置保存接口
- 管理令牌：浏览器会话存储 → `x-admin-token` → `security.py`
- 备份、回滚、审计、服务重启：`control_extensions.py`

### 审查结论

1. 接口端已经能通过表单完成绝大多数常用配置，不需要直接编辑文件。
2. 原主题是固定浅色普通管理后台，缺少夜间模式和跨页面主题状态。
3. 页面功能完整，但视觉层级、按钮状态、移动端布局和配置影响提示不够清楚。
4. 本次不改变配置文件格式、不绕过令牌、不改变保存和重启语义。

## 2. 实施范围

### P1 统一主题基础设施

- 新增独立主题模块。
- 使用 CSS 变量实现 iOS 玻璃质感、半透明面板、背景光晕、圆角和柔和阴影。
- 支持 `light`、`dark`、`system` 三种模式。
- 主题保存到浏览器 `localStorage`，刷新后保持。
- 跟随系统模式时监听系统主题变化。

### P2 日常操作优化

- 在顶部加入主题切换控件。
- 强化主操作、危险操作、次要操作的视觉区分。
- 改善表单、开关、表格、日志、状态卡片、Toast 和移动端体验。
- 保留全部现有标签页、管理令牌和高级功能。

### P3 安全与兼容

- 不引入第三方 CDN、字体或外部脚本。
- 不记录或持久化管理令牌到长期存储。
- 不修改后台 API 和配置结构。
- 旧浏览器不支持 `backdrop-filter` 时自动退化为不透明面板。

### P4 验证

- Python 单元测试全部通过。
- WebUI JavaScript 生成和 `node --check` 通过。
- 新增主题契约测试：主题控件、三模式、存储键、系统模式监听、移动端样式必须存在。

## 3. 进度

- [x] AUDIT：页面、配置、权限和保存链路审查
- [x] PLAN：范围、兼容和验收标准确定
- [ ] IMPLEMENT：主题模块与运行时注入
- [ ] VERIFY：单元测试和 WebUI 语法验证
- [ ] COMPLETE：合并并标记完成

## 4. 完成标准

只有同时满足以下条件才能标记 `COMPLETED`：

1. 白天、夜间、跟随系统三种模式可在页面直接切换。
2. 主题在刷新和重新打开页面后保持。
3. 所有接口端标签页仍可读取和保存原配置。
4. 管理令牌、安全保护、备份回滚和服务管理保持有效。
5. 全量 CI 通过并合并到 `master`。
