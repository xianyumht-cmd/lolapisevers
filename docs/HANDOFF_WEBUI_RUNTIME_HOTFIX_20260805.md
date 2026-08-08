# HANDOFF：6178 WebUI 运行时热修复

- 项目：`xianyumht-cmd/lolapisevers`
- 日期：2026-08-05
- PR：`#39`
- 工作分支：`feat/query-console-lolban-20260804`
- 当前生产提交：`28e68e75ee14674bba10606587937473d37baa1e`
- 修复基线提交：`10e1ebcf040bf59fa4b0875418cd051c8de770a4`
- 当前状态：代码修复完成，本地 313 项测试通过，等待 GitHub CI、V3 候选包与生产实机验收

## 1. 实机发现的问题

### 4PNG Token 保存后仍统一返回 503

用户在封号页填写 `LOL_BAN_4PNG_TOKEN` 后，Provider 测试和正式链路仍返回：

```json
{
  "code": 503,
  "msg": "查询失败：接口繁忙，请稍后再试",
  "data": {},
  "ok": false,
  "status_code": 503
}
```

根因不是用户 Token 格式，而是进程边界：Secret 只写入本地配置并加载到 6178 进程，真正执行封号 Provider 的 5001 进程没有加载 `LOL_BAN_4PNG_TOKEN`。所有 Provider 失败后，正式链路只返回统一的安全 503。

### 解析中心与 Secret 页面点击无反应

`/parser-center` 后端 API 与 HTML 都存在，但页面脚本 `renderResponseTree` 少一个右花括号，浏览器加载 JavaScript 时产生 `Unexpected end of input`。因此页签、Provider 编辑、Secret、备份和回滚按钮全部失效，看起来像占位页。

此前 CI 只校验根控制台和封号页脚本，没有校验解析中心最终渲染脚本，因此没有在候选阶段拦截。

## 2. 本次修复

### 4PNG Secret 与 5001 热加载

- `LOL_BAN_4PNG_TOKEN` 加入 5001 严格热加载白名单。
- 封号页新增专用保存端点：`POST /admin/query-console/lolban/4png-token`。
- 保存流程：安全写入本机环境配置 → 不回显 Token → 立即热加载 5001。
- 页面分别显示磁盘已配置与 5001 已加载状态。
- 只有热加载失败时才提示手动重启服务。
- 运行态诊断只返回 Secret 是否配置，不返回 Secret 内容。

### 解析中心页面恢复

- 修复 `renderResponseTree` 缺失右花括号。
- 新增真实页面路由：
  - `/parser-center`
  - `/parser-center/secrets`
  - `/parser-center/advanced`
- 左侧菜单改用独立路径，不再依赖容易失效的查询参数切换。
- Secret 与备份页面由服务端直接选中对应区域，JavaScript 未运行前也不会显示错误页签。
- 移除对 `CSS.escape` 的依赖，兼容当前生产浏览器。

### 测试和诊断改进

- Provider 直连与 5001 正式链路改为两个独立测试按钮，避免一个 503 看起来像所有接口同时失败。
- Provider 失败增加安全分类：Secret 未加载、配置错误、超时、网络错误、业务拒绝、响应无效等。
- 不返回第三方原始广告、Token、URL 或异常正文。
- CI 现在渲染并校验根控制台、解析中心、Secret 页面和封号页的每段 JavaScript。
- 页面脚本语法错误会直接阻断候选包。

## 3. 已完成验证

本地完整依赖环境中：

- 313 项测试通过；
- Python 全仓编译通过；
- 根控制台、解析中心、Secret 页面、Advanced 页面、封号页均返回 HTTP 200；
- 各页面最终渲染后的每段 JavaScript 均通过 `node --check`；
- Secret 不回显、严格热加载白名单和安全诊断测试通过。

## 4. 生产状态与下一步

当前生产仍运行 `28e68e75...`，所以用户看到的统一 503 和解析中心按钮失效问题仍然存在，不能仅靠刷新解决。

下一步：

1. 等待最终 GitHub Linux、Windows、Parser Center、依赖审计和 V3 包内测试通过。
2. 下载并复核新 V3 离线部署包。
3. 用户运行 `run-deploy.cmd`。
4. `Ctrl + F5` 刷新 6178。
5. 验收 `/parser-center`、`/parser-center/secrets`、4PNG Token 保存与热加载。
6. 分别测试 `LOL2099`、`4PNG` 的 Provider 直连和正式链路。
7. 实机通过后再决定是否合并 PR #39。

## 5. 不应回退的原则

- Secret 只能保存在服务端配置，不直接写入 Provider JSON 或 URL。
- 6178 与 5001 是不同进程，涉及运行时 Secret 时必须明确同步状态。
- WebUI 必须验证最终渲染页面脚本，而不只是源文件片段。
- 第三方广告、来源、域名、Token 和原始异常不得进入群内公开消息。
