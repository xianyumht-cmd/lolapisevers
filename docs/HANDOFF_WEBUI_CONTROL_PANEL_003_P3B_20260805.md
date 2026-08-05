# WEBUI-CONTROL-PANEL-003 P3B 交接

## 当前状态

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- P3B 功能提交：`3c7a8868020eecee9cffbfca70d96e2766ba8f5c`
- PR 与 Issue 在整体 WebUI 迁移完成前保持打开；PR 保持 Draft。

P3A 已于 2026-08-05 在 Windows 生产机部署并通过实机验收：333 项测试、Windows 服务、`livez`、`readyz`、build-info、Git HEAD、合集和 ARAM 正式交付链路均通过，verification report 为 `pass`。

P3B 已完成分支实现，尚未部署生产。

## P3B 已迁移页面

- `/main-config`：主接口配置；
- `/lanzou/config`：蓝奏全局配置；
- `/lanzou/watchers`：监控项目；
- `/lanzou/targets`：通知目标；
- `/api-debugger`：接口调试器。

对应旧地址保留 307 兼容重定向：

- `/?tab=mainconfig` → `/main-config`；
- `/?tab=lanzouconfig` → `/lanzou/config`；
- `/?tab=watchers` → `/lanzou/watchers`；
- `/?tab=targets` → `/lanzou/targets`；
- `/?tab=debugger` → `/api-debugger`。

P3A 的日志、诊断、安全与回滚重定向继续保留。

## 页面与交互

P3B 页面统一使用现有共享控制台 Shell：

- Sidebar、Topbar、面包屑；
- 管理令牌 Dialog；
- Toast、Loading、Empty、Badge、Table、Form；
- 本地 SVG 图标；
- `configuration.css` 与 `configuration.js`；
- 不依赖外部 CDN；
- 不使用浏览器原生 `alert`、`confirm` 或 `prompt`。

### 主接口配置

- 按后端字段元数据分组渲染；
- 支持文本、数字、布尔和 Secret 字段；
- Secret 不回显，留空表示保留原值；
- 保存继续调用 `/admin/main-config`；
- 后端继续校验、备份，并明确提示需要重启服务生效。

### 蓝奏全局配置

- 继续调用 `/admin/lanzou-config`；
- 保存后刷新运行态；
- 监听地址或端口变化仍明确提示需要重启；
- 环境变量覆盖项单独显示，不能被页面误认为普通配置值。

### 监控项目

- 支持新增、编辑、启停和删除 watcher；
- 密码字段只显示配置状态；
- 空白或 `***` 表示保留原密码；
- 只有显式 `clear_password` 才清除密码；
- 支持读取文件快照和执行单项扫描；
- 保存继续走现有蓝奏配置校验、备份和热刷新流程。

### 通知目标

- 支持新增、编辑、启停和删除目标；
- Header 中 Token、Authorization、Cookie、API Key 等敏感值脱敏；
- `***` 保存时保留原值；
- 支持测试推送；
- 真实凭据不进入页面源码、公开状态或普通日志。

### 接口调试器

- 继续复用 `/admin/openapi/main`、`/admin/openapi/lanzou` 和 `/admin/invoke`；
- 支持服务、接口、方法、Path、Query、Header 和 JSON Body；
- 调用结果以等宽只读结果展示；
- 5001 写入令牌由服务端按现有规则注入，不回传浏览器。

## 安全与兼容

- 页面壳和静态资源公开可加载；
- 管理 API 继续受本机回环或 `WEBUI_ADMIN_TOKEN` 保护；
- 令牌只进入当前标签页 `sessionStorage`；
- 401/403 自动打开管理令牌 Dialog；
- GET `/admin/lanzou-config` 返回脱敏配置；
- Watcher 密码和通知 Header 支持掩码往返保留；
- 现有后端 API 路径、配置 Schema、Provider 协议和插件协议不变。

## 已完成验证

P3B 补丁经过以下门禁后才形成正式功能提交：

- gzip/Base64 载荷完整性；
- 补丁精确大小 91,523 字节；
- `git apply --check`；
- Python 编译；
- 338 项单元测试；
- `tests/check_ui_assets.py`；
- `configuration.js` 执行 `node --check`；
- 临时补丁载荷和临时工作流已自动删除；
- 原正式 `tests.yml` 已恢复。

功能提交后还需要完成标准 GitHub CI：

- Linux 全量测试；
- Windows 全量测试；
- Parser Center 专项及全套测试；
- 所有最终 WebUI JavaScript；
- 全部 PowerShell 5.1；
- 依赖安全审计。

## 下一步

1. 等待 P3B 文档提交触发的最终标准 CI 全绿；
2. 更新 PR #41、Issue #40 与 CHANGELOG；
3. 以当前生产 `7d637b90...` 为第一父提交，构造文件树等于 P3B 候选的部署提交；
4. 构建 V3 不可变离线一键部署包；
5. Windows 实机验收五个 P3B 页面及旧 `?tab=` 重定向；
6. P3B 验收完成后再审查并退休 `ui_control.py`、`ui_runtime.py`、旧导航注入和 `/legacy-ui` 应急页。
