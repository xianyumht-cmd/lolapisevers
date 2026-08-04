# WEBUI-CONTROL-PANEL-003：统一设计系统与页面重构

- Issue：#40
- 分支：`feat/webui-control-panel-003-20260805`
- 功能基线：`d1500c17c08dad287c76b9e1763037860eccc567`
- 依赖：PR #39 完成生产实机验收
- 当前阶段：P0 已在 Draft PR #41 实现，等待 V3 候选包与 Windows 实机视觉验收

## 1. 目标

把 6178 从“旧页面 + 注入侧栏”的过渡实现，重构为真正统一的运维控制台。

本阶段只改变前端页面结构、视觉组件和交互组织，不改变现有后端 API、Provider 协议、Secret 规则、配置 Schema、插件协议和公开消息格式。

## 2. 核心原则

1. 不再通过全局 HTML 中间件给旧页面继续叠加样式作为最终方案。
2. 页面统一使用共享布局、共享设计令牌和共享组件。
3. 所有生产操作继续走现有真实后端 API。
4. 新旧页面并行一段时间，实机验收通过后再移除旧入口。
5. 所有资源必须进入离线部署包，不依赖外部 CDN。
6. 最终渲染后的每段 JavaScript 都必须进入 CI 语法检查。
7. Secret、Token、第三方域名、广告和原始异常不得出现在公开输出中。

## 3. 设计方向

### 页面外壳

- 固定左侧导航；
- 顶部栏；
- 面包屑；
- 页面标题、说明与主要操作区；
- 内容工作区；
- 统一全局 Toast、Dialog、Drawer 和 Loading 层。

### 视觉语言

- 页面背景：浅灰；
- 内容区：白色面板；
- 边框：细边框；
- 圆角：小圆角；
- 阴影：轻阴影或无阴影；
- 主色：蓝色，仅用于主操作、链接和选中态；
- 去除大面积渐变、毛玻璃和重阴影。

### 字体

普通中文界面：

```css
font-family:
  "Microsoft YaHei UI",
  "Microsoft YaHei",
  "微软雅黑",
  "Segoe UI",
  sans-serif;
```

代码、JSON 和日志：

```css
font-family:
  "Cascadia Mono",
  "SFMono-Regular",
  Consolas,
  monospace;
```

### 图标

- 使用统一的本地 SVG 图标集；
- 不再以“首页、封号、解析、密钥”等文字充当图标；
- 图标必须有一致尺寸、线宽和对齐方式。

## 4. 技术结构

当前已建立：

```text
lanzou_update_push_api_server/control_ui/
  __init__.py
  components.py
  pages.py
  assets/
    console.css
    console.js
    icons.svg
```

当前结构职责：

- `components.py`：Icon、导航、Sidebar、Topbar、管理令牌 Dialog、Console Shell；
- `pages.py`：总览页业务内容；
- `console.css`：共享设计令牌和组件样式；
- `console.js`：统一 API 请求、管理令牌、错误分类、Loading 和 Toast；
- `icons.svg`：离线本地图标集。

原则：

- 页面由服务端模板/组件组合生成；
- CSS 与 JavaScript 使用静态资源路由集中提供；
- 不在每个页面复制整套 CSS；
- 不在每个页面重复侧栏、顶栏、令牌 Dialog 和 Toast；
- 后端 API 调用统一封装，管理令牌、错误处理和 Toast 统一实现。

## 5. 分阶段执行

## P0：设计系统与总览骨架

### 当前状态

已完成分支实现，包含：

- 新控制台布局；
- 设计令牌；
- 导航、顶栏、面包屑；
- Button、Input、Badge、Card、Table、Empty、Skeleton、Toast、Dialog；
- 新总览页；
- 旧版入口；
- 5001/6178 状态、Provider 状态、降级项、最近修改、最近错误和快捷操作；
- 管理令牌会话存储与 401/403 自动处理；
- 共享 Shell 和组件拆分；
- 静态资源鉴权边界修复。

Drawer 将在 P1 Provider 编辑场景中完成实际组件落地，避免只增加没有真实使用场景的空实现。

### 验收

- 总览页不再使用旧毛玻璃页面；
- 桌面端和窄窗口均可使用；
- 导航和顶部栏视觉一致；
- 所有状态数据来自现有真实 API；
- 旧版入口仍可回退；
- 管理令牌开启后根页与静态资源正常加载；
- 管理 API 仍保持鉴权保护。

## P1：封号查询页

### 实现

- Provider 表格；
- 排序、启停和状态；
- 编辑抽屉；
- 4PNG Token 状态；
- Provider 直连测试；
- 正式链路测试；
- 错误分类和脱敏结果；
- 保存、热加载、磁盘/运行态一致性。

### 验收

- 不再一次铺开所有 Provider JSON 表单；
- 不使用浏览器原生 `alert/confirm`；
- Secret、URL 和异常内容不泄漏；
- 现有 API 契约保持不变。

## P2：解析中心与 Secret/备份

### 实现

- 功能与 Provider 双栏导航；
- 可视化编辑器；
- Advanced JSON；
- 请求测试与响应树；
- 公开文本预览；
- Secret 独立页面；
- 备份列表、差异提示和回滚确认。

### 验收

- `/parser-center`、`/parser-center/secrets`、`/parser-center/advanced` 独立可用；
- 不依赖隐藏旧页签；
- 保存、测试、备份和回滚均调用现有 API。

## P3：其余页面迁移

- 蓝奏全局配置；
- 监控项目；
- 通知目标；
- 主接口配置；
- 日志；
- 诊断；
- 安全与回滚；
- 接口调试器。

## 6. 测试要求

每一阶段都必须完成：

- Python 编译；
- 后端 API 契约测试；
- 页面渲染测试；
- 最终 HTML 中所有脚本提取并执行 `node --check`；
- 路由与导航测试；
- Secret 脱敏测试；
- 关键操作交互测试；
- Windows 与 Linux 全量测试；
- PowerShell 5.1 解析；
- 依赖审计；
- V3 不可变离线候选包；
- Windows 生产机实机验收。

P0 当前已覆盖页面结构、组件转义、活动菜单、真实路由、静态资源、管理令牌边界、新旧回退路径和 WebUI JavaScript 语法检查。

## 7. 发布策略

1. PR #39 先完成当前运行时修复的实机验收。
2. 本分支从 `d1500c17...` 建立，不把视觉重构塞回 PR #39。
3. P0 使用独立 Draft PR #41。
4. 每个阶段提供独立候选包和回滚点。
5. 新页面未全部验收前，保留旧版入口。
6. 全部页面迁移完成并稳定后，再删除旧 HTML 注入实现。

## 8. 下一步

1. 完成最新 P0 组件拆分提交的 Linux、Windows、Parser Center 和脚本检查；
2. 更新 PR #41 与 Issue #40 的最终 P0 记录；
3. 生成锁定提交的 V3 不可变离线预览包；
4. 在 Windows 实机打开 6178，检查布局、字体、导航、令牌 Dialog、状态卡和窄窗口；
5. P0 实机验收通过后进入 P1：封号查询表格与编辑 Drawer。
