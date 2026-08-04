# WEBUI-CONTROL-PANEL-003 P0 实机验收与修复交接

- Issue：#40
- Draft PR：#41
- 分支：`feat/webui-control-panel-003-20260805`
- 首次生产预览提交：`5a1f6420867e289a9dc36b6ef62fa116b8b47880`
- 当前修复候选：`153106dec8a49ee7ebdf8f6f35b8df6d09a5bcdc`
- 日期：2026-08-05

## 1. 首次生产部署结果

P0 首个 V3 包已在 Windows 生产机成功部署到 `5a1f6420867e289a9dc36b6ef62fa116b8b47880`。

部署证据：

- 候选环境安装与依赖检查成功；
- 324 项测试全部通过；
- 生产服务切换成功；
- `/livez` HTTP 200；
- `/readyz` HTTP 200；
- `/build-info` 与 Git HEAD 均匹配目标提交；
- shard 与 ARAM 正式交付链路通过；
- verification report 状态为 `pass`；
- 生产备份位于仓库外部部署备份目录。

## 2. 实机页面验收结论

新 6178 根控制台的结构和视觉方向已达到 P0 目标：

- 固定深色侧栏；
- 白色顶栏与面包屑；
- 微软雅黑中文字体；
- 状态卡、Provider 表格、快捷入口和告警面板；
- 本地 SVG 图标；
- 不再使用旧毛玻璃根页面；
- 信息密度和层级明显优于旧版控制台。

P0 不能直接判定最终通过，因为截图暴露了两项真实问题。

## 3. 实机发现的问题

### 3.1 6178 被错误标记为异常

旧总览把 `overview.lanzou.health` 当成 6178 WebUI 服务健康。

该字段实际描述蓝奏监控任务状态。当部分 watcher 失败、未扫描、等待确认或存在孤儿状态时，它可以返回 `degraded`，但 6178 页面和管理 API 仍然正常。

结果是：

- 6178 状态卡错误显示“需要关注/异常”；
- 顶栏错误显示红色服务异常；
- 告警列表错误出现“6178 监控状态异常”。

### 3.2 4PNG Token 磁盘已配置但 5001 启动后未加载

Token 已安全写入 `ops/app_env.local.ps1`，但生产服务启动链对 PowerShell 环境继承存在依赖。实机重启后，5001 的 `os.environ` 仍可能缺少 `LOL_BAN_4PNG_TOKEN`。

结果是：

- 磁盘状态显示已配置；
- 运行态状态显示未加载；
- 4PNG Provider 无法使用已保存 Token。

## 4. 已完成修复

### 4.1 状态语义修复

总览现在分开判断：

- 6178 控制台是否可访问：以 `/build-info` 和控制面响应为准；
- Windows 托管服务状态：读取服务状态对象的 `state/status`；
- 蓝奏监控业务降级：单独显示为“蓝奏监控任务存在降级”。

全局状态改为三档：

- 绿色：核心服务正常且没有告警；
- 黄色：核心服务正常，但存在业务告警；
- 红色：5001 或 6178 核心服务实际异常。

### 4.2 Python 启动环境兜底

新增 `core/local_env.py`：

- 在导入封号路由和服务前读取 `ops/app_env.local.ps1`；
- 只解析字面量 `$env:KEY = VALUE`；
- 不执行 PowerShell；
- 忽略表达式和不安全语句；
- 不覆盖已经存在的环境变量；
- 不记录或返回 Secret 值。

这使 `LOL_BAN_4PNG_TOKEN` 在 NSSM/PowerShell 环境继承不完整时仍能由 Python 安全加载。

### 4.3 生成物防线

全量测试曾生成：

- `config/interface-parser-center.json`；
- `data/contact_risk.db`。

两项均已从候选树删除，并加入 `.gitignore`。同时忽略三套生成的 JavaScript 检查文件，防止测试产物进入后续提交和部署包。

## 5. 测试结果

修复候选 `153106dec8a49ee7ebdf8f6f35b8df6d09a5bcdc` 已通过：

- Linux 全量测试；
- Windows 全量测试；
- 327 项测试；
- Parser Center 专项及全套测试；
- 新控制台、封号页、解析中心 JavaScript 语法检查；
- 全部 PowerShell 5.1 解析；
- 依赖安全审计；
- 环境加载器不覆盖已有变量测试；
- 环境加载器拒绝执行 PowerShell 表达式测试；
- 应用启动顺序测试；
- 状态语义回归测试。

## 6. 当前生产与下一步

当前生产仍运行 `5a1f6420867e289a9dc36b6ef62fa116b8b47880`。

`153106dec8a49ee7ebdf8f6f35b8df6d09a5bcdc` 尚未部署。下一步必须：

1. 为当前修复候选生成新的 V3 不可变离线包；
2. 在 Windows 生产机运行 `run-deploy.cmd`；
3. 确认 6178 卡片显示运行正常；
4. 若蓝奏 watcher 有问题，只显示业务降级，不再显示 6178 服务异常；
5. 确认 4PNG Token 的磁盘和 5001 运行态均为已配置；
6. 执行 4PNG Provider 直连与正式链路测试；
7. 验收完成前 PR #41 保持 Draft。
