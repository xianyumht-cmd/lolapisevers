# HANDOFF：6178 专业控制面板与查询配置

- 项目：`xianyumht-cmd/lolapisevers`
- 任务编号：`WEBUI-CONTROL-PANEL-002`
- 日期：2026-08-05
- 工作分支：`feat/query-console-lolban-20260804`
- PR：`#39`
- 基线生产提交：`19edfc9c189f6b269793ed750e42548268fcc115`
- 当前状态：代码实现与本地验证完成，等待 GitHub CI、V3 候选包和生产实机验收

## 1. 用户要求

1. `/parser-center` 不能像占位页面，必须有真实可操作功能并从主面板进入。
2. `http://127.0.0.1:6178/` 当前排版杂乱，需要改为类似宝塔控制面板的专业可视化后台。
3. 使用菜单和折叠分组管理功能，而不是继续横向堆按钮和卡片。
4. 4PNG Token 应能在 WebUI 直接安全配置，用户不应修改 Provider JSON 中的 `$secret:LOL_BAN_4PNG_TOKEN`。
5. 最近更新需要进入更新日志，并留下新聊天可继续的交接文档。

## 2. 审查结论

`/parser-center` 并非空实现。它已有以下真实后端链路：

- `GET /admin/parser-center`：读取当前正式配置、Secret 配置状态。
- `POST /admin/parser-center`：Schema 校验、备份和原子保存。
- `POST /admin/parser-center/test`：使用当前页面 Provider 发起真实请求并预览解析结果。
- `POST /admin/parser-center/secret`：把当前配置引用的 Secret 安全写入本机环境文件，值不回显。
- `GET /admin/parser-center/backups`：读取备份。
- `POST /admin/parser-center/rollback`：回滚前再次备份当前版本。

问题主要在页面信息架构：入口缺失、页面孤立、专业功能被工程化布局隐藏，因此用户感受像占位页。

## 3. 本阶段实现

### 统一控制台导航

新增 `lanzou_update_push_api_server/control_navigation.py`，对根控制台、封号页和解析中心统一注入：

- 固定左侧导航栏；
- 折叠菜单分组；
- 当前页面高亮；
- 移动端抽屉菜单；
- URL 查询参数打开原有功能页签；
- 统一生产安全提示。

导航分组：

- 查询服务：封号查询、接口与解析中心、Secret 与备份、接口调试器；
- 蓝奏监控：全局配置、监控项目、通知目标；
- 系统管理：主接口配置、运行日志、诊断修复、安全回滚；
- 开发与文档：OpenAPI、旧版控制台。

原有横向页签保留在 DOM 中以维持现有逻辑，但在新控制台模式下隐藏，由左侧菜单通过 URL 参数激活。

### 解析中心入口与真实功能

- 根面板左侧菜单新增 `/parser-center?section=visual`。
- Secret 入口新增 `/parser-center?section=backups`。
- Provider 编辑、请求测试、公开文本预览、Secret 保存、备份与回滚继续调用真实管理 API。
- 未改变解析中心配置 Schema 或生产接管规则。

### 4PNG Token 直接配置

`/query-console/lolban` 新增“4PNG Token”区域：

- 固定 Secret 名称 `LOL_BAN_4PNG_TOKEN`；
- 用户只输入真实 Token；
- 保存调用 `/admin/parser-center/secret`；
- Token 不回显，不写入 Provider JSON 或 URL；
- 页面显示已配置/未配置状态；
- 提供受控重启 `LOLDataSystem` 的入口；
- Provider JSON 中继续保留 `$secret:LOL_BAN_4PNG_TOKEN`。

### 文档

- 新增根目录 `CHANGELOG.md`，记录 2026-07-30 至 2026-08-05 的主要更新。
- 本文件作为当前任务最新交接文档。

## 4. 变更文件

- `lanzou_update_push_api_server/control_extensions.py`
- `lanzou_update_push_api_server/control_navigation.py`（新增）
- `tests/test_control_navigation.py`（新增）
- `CHANGELOG.md`（新增）
- `docs/HANDOFF_LATEST.md`（新增）
- `docs/HANDOFF_LATEST_WEBUI_CONTROL_PANEL_20260805.md`（新增）

实现采用 6178 统一 HTML 中间件装饰现有页面，不重写根控制台、解析中心或封号页面的业务路由，因此原有管理 API、表单保存、备份和查询逻辑保持不变。

## 5. 已完成验证

本地候选源码已完成：

- Python 全仓编译；
- 新增控制台导航单元测试；
- 封号页原有安全测试；
- 根控制台与封号页 JavaScript 提取；
- `node --check` 页面脚本语法验证；
- 导航幂等注入验证；
- 解析中心真实 API 标记验证；
- 4PNG Token 专用输入与 Secret 接口标记验证。

## 6. 待完成步骤

1. 把本阶段变更提交到 PR #39 分支。
2. 等待 Linux、Windows、Parser Center、依赖审计和 V3 安全打包全绿。
3. 下载并复核 V3 离线部署包 SHA-256。
4. 用户运行 `run-deploy.cmd`。
5. 实机验收：
   - 根页显示左侧折叠菜单；
   - 主面板可进入解析中心；
   - `/parser-center?section=backups` 能显示并保存 `LOL_BAN_4PNG_TOKEN`；
   - 封号页能直接保存 Token；
   - 重启后 4PNG Provider 直连和 5001 正式链路通过；
   - LOL2099 Provider 直连和正式链路通过。
6. 实机验收后更新本文件状态，并决定是否将 PR #39 从 Draft 转为可合并。

## 7. 不应回退的设计原则

- 插件端只负责请求和消息交付，业务解析留在 Windows 接口端。
- Secret 不直接写在 URL、Provider JSON、日志或浏览器响应中。
- 新 Provider 默认关闭，先测试后启用。
- 配置保存必须校验、备份并支持回滚。
- 第三方广告、来源字段和域名不得进入用户公开消息。
