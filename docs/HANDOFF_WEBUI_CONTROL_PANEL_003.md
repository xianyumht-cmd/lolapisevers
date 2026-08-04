# WEBUI-CONTROL-PANEL-003 交接与更新日志

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 功能基线：`d1500c17c08dad287c76b9e1763037860eccc567`
- 当前阶段：P0 设计系统与控制台总览实现中
- 生产状态：本分支尚未部署；禁止仅根据 GitHub 分支状态宣称生产已更新

## 1. 项目目标

把 6178 WebUI 从“旧页面加注入侧栏”的过渡实现，逐步重构为统一、可复用、可测试的正式运维控制台。

本任务保留现有后端 API、Provider Schema、Secret 规则、配置格式、插件协议和公开消息格式，不在视觉重构中改变业务契约。

## 2. P0 已完成内容

### 2.1 新控制台总览

- `/` 和 `/ui` 已改为独立的新控制台总览；
- 根页不再渲染旧毛玻璃页面，也不再依赖旧导航注入；
- `/legacy-ui` 保留原始控制台回退；
- `/?tab=...` 旧功能入口继续保留，等待 P3 分批迁移。

### 2.2 统一视觉基础

- 浅灰工作区、白色内容面板、细边框、小圆角、轻阴影；
- 去除根控制台大面积渐变和毛玻璃效果；
- 普通中文固定使用微软雅黑字体栈；
- 代码、JSON、路径和日志使用等宽字体；
- 本地 SVG 图标集，不依赖 CDN；
- 桌面固定侧栏、顶部栏、面包屑、页面标题区和内容工作区；
- 窄窗口使用可关闭的侧栏抽屉。

### 2.3 总览数据

新总览直接读取现有真实 API：

- `/admin/overview`
- `/admin/query-console/lolban`
- `/admin/audit`
- `/admin/logs`
- `/admin/service/status`
- `/build-info`

页面展示：

- 5001 主接口状态；
- 6178 控制台状态；
- 封号 Provider 磁盘与运行态；
- 当前降级项；
- 最近配置变更；
- 日志摘要；
- 常用管理入口。

### 2.4 管理令牌流程

- 顶栏新增“管理令牌”；
- 使用统一 Dialog，不使用浏览器原生 `prompt`、`alert` 或 `confirm`；
- 令牌只保存到当前标签页的 `sessionStorage`；
- 关闭标签页后自动清除；
- 不写入服务配置、HTML 或 JavaScript；
- 管理接口返回 401/403 时自动打开令牌 Dialog；
- 可重新保存或清除当前标签页令牌；
- 各失败接口在页面中分别显示原因，不再只提示“读取失败”。

### 2.5 Loading、Toast 与错误状态

- 核心状态卡使用 Skeleton；
- 表格和列表使用统一 Loading；
- Toast 区分信息、成功和失败；
- Provider、审计和日志读取失败时在各自面板显示明确错误；
- 管理令牌失败单独归类为访问控制问题。

### 2.6 静态资源安全边界

开发过程中真实路由测试发现 `/control-assets/*` 被控制面鉴权中间件拦截，导致新页面 HTML 能打开但 CSS、JavaScript 和 SVG 返回 403。

修复后：

- 仅 `/control-assets/` 前缀作为公开只读静态资源；
- 相邻管理路径不因此前缀放宽权限；
- 配置 `WEBUI_ADMIN_TOKEN` 后，根页和静态资源仍可读取；
- `/admin/*` 仍必须通过管理令牌验证。

### 2.7 可复用组件结构

已从总览页拆出：

- 统一 SVG Icon 调用；
- 导航数据与活动菜单；
- Sidebar；
- Topbar；
- 管理令牌 Dialog；
- 完整 Console Shell。

当前目录：

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

后续 P1、P2 页面必须复用这些组件，不再复制整套侧栏、顶栏和访问控制 Dialog。

## 3. 测试覆盖

当前已增加：

- 新总览静态结构测试；
- 共享组件测试；
- 活动菜单唯一性测试；
- HTML 属性和文本转义测试；
- 根页真实 FastAPI 路由测试；
- CSS、JavaScript、SVG 静态资源路由测试；
- 配置管理令牌后的静态资源公开边界测试；
- 管理 API 仍受保护的回归测试；
- `console.js` Windows `node --check`；
- 原封号页和解析中心最终脚本语法检查继续保留；
- Linux、Windows 全量测试；
- PowerShell 5.1 解析；
- 依赖安全审计。

## 4. 近期更新日志

### 2026-08-05 · P0 第一批

- 新建独立控制台总览；
- 建立共享 CSS、JavaScript 和 SVG 资源目录；
- 根页面退出旧毛玻璃渲染链；
- 加入服务、Provider、降级、审计和日志摘要；
- 保留旧版回退入口；
- 建立 Draft PR #41。

### 2026-08-05 · P0 第二批

- 修复静态资源被鉴权拦截的 403；
- 增加管理令牌 Dialog；
- 增加 401/403 自动识别；
- 增加 Skeleton、Loading 和分类 Toast；
- 增加各 API 独立错误展示；
- 去除顶栏残留玻璃效果。

### 2026-08-05 · P0 第三批

- 新增 `components.py`；
- 拆出 Sidebar、Topbar、导航、图标、Dialog 和 Console Shell；
- 总览页改为组合共享 Shell；
- 增加组件转义和结构测试。

## 5. 未完成与下一步

1. 等待最新组件拆分提交完成 Linux、Windows 和 Parser Center CI；
2. 更新 PR #41 描述与 Issue #40 进度；
3. 生成 P0 V3 不可变离线预览候选包；
4. 在 Windows 实机打开 6178，完成视觉和交互验收；
5. P0 通过后进入 P1：封号 Provider 表格、编辑 Drawer、直连测试和正式链路测试重构。

## 6. 发布与回滚规则

- PR #41 保持 Draft，未实机验收前不合并；
- 不直接部署开发分支源码；
- 只使用锁定提交、带清单、离线依赖、备份和自动回滚的 V3 包；
- 部署前候选测试必须在生产停止前完成；
- 部署后必须验证 `/livez`、`/readyz`、`/build-info`、6178 根页和静态资源；
- 新页面异常时优先使用 `/legacy-ui` 回退，必要时执行完整版本回滚。
