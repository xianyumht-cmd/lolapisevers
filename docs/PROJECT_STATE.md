# Project state

更新时间：2026-08-28 +08:00

## Canonical development

- 默认开发分支：`master`；GitHub 实际 `master` 提交是开发状态最终依据。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；仓库改动、CI 和本地引导包不等于生产已部署。
- 当前 `master` / 已发布 Release `lolapi-e0dbf15c15d2` 的目标提交为 `e0dbf15c15d24fc13609679c9ad7ddfd35e6c4d1`，其中 PR #95 已完成查询图片延迟 P0。
- 2026-08-28 生产运行时仍停留在 `2135a13a23b96fe2455d3a53311b35bd93dd22da`；从 WebUI 升级 `e0dbf15c...` 时，83 MB V3 包已通过 `github-cdn-6x` 下载到 100%，但候选测试阶段在生产停止/切换前失败，因此生产未改变。
- 当前修复任务：Issue #96，分支 `fix/winps51-python-stderr`。目标是修复 WinPS 5.1 将 Python/Node 的正常 stderr 输出误判为部署失败的问题。

## 已完成：查询图片延迟 P0（Issue #94 / PR #95）

- 战绩、段位、海符统计等业务数据继续走既有第三方 upstream / snapshot 新鲜度策略；图片优化没有把实时业务数据替换成长 TTL 结果。
- 图片素材 CDN 已从正常用户查询关键路径移除：本地已有素材直接使用，本地缺失时立即用占位继续渲染并后台补资源。
- 字体加载使用进程内 LRU；`fit_text` 使用二分测量；PNG 在线编码改为低延迟压缩路径。
- 战绩 PNG 使用 120 秒服务端最终图缓存，key 绑定可见业务字段、renderer version 和 footer；业务数据变化即 miss。
- 素材未齐时响应为 `warming` 且不写最终图缓存，后台资源补齐后下一次查询重绘完整版本。

## 当前阻塞：WinPS 5.1 原生命令 stderr 误杀候选测试

生产 `update.log` / `launch.log` 的可重复证据：

- Task Scheduler / SYSTEM helper 正常启动，PID 15740 与 13064 都进入 `1/6 Build isolated candidate environment while production stays running`。
- 候选 Python 为生产 `.venv\Scripts\python.exe`，版本 Python 3.14。
- 离线 wheel 安装与 `pip check` 成功。
- `tests/test_winps51_git_stderr.py` 中 `Function:\Invoke-Git` 的 Python 字符串触发 `SyntaxWarning: "\I" is an invalid escape sequence`。
- V3 deployer 仍直接执行 `& $candidatePython ...`；在 Windows PowerShell 5.1 且 `$ErrorActionPreference = "Stop"` 时，这个 stderr 被转换为终止错误，部署进程 ExitCode=1。
- 日志明确记录 `Production was not stopped or changed.`，所以这是候选预检的 fail-closed，生产没有发生半切换。

Issue #96 修复要求：

1. 修正当前 Python 无效转义，新增全仓 Python `SyntaxWarning` 回归检查。
2. V3 Release artifact 将候选 Python/Node 调用改为 `System.Diagnostics.Process` 包装：stdout/stderr 均捕获进日志，只有真实非零 ExitCode 才失败。
3. 保留既有 Git stderr-safe 包装；新增 `winps51_native_process_stderr_safe` metadata / manifest 安全标志。
4. V3 CI 必须验证最终 ZIP 内没有候选阶段的直接 `& $candidatePython` / `& $node.Source` 调用，并验证安全 wrapper marker。
5. Windows 单测必须模拟“stderr 有 warning + ExitCode 0”通过、“ExitCode 非 0”失败，防止再次出现假失败。

## Release 更新安全边界

- GitHub Release Token 只发送到 GitHub 官方 API；第三方公共镜像永不携带 Token。
- Release metadata 继续通过 GitHub 官方认证链获取；最终 ZIP 必须通过 metadata SHA-256、路径安全检查、V3 manifest 安全标志与 target commit 校验。
- GitHub Compare 只有 `current...target = ahead` 才允许自动前向升级；`behind`、`diverged` 或关系未知均 fail-closed。
- 部署由 Task Scheduler / SYSTEM 托管；V3 deployer 先做候选测试，再做备份/生产切换/后置验证，失败时自动回滚。
- 已验证 ZIP 下载成功不等于部署成功；候选预检失败时必须保留当前生产并显示明确失败阶段。

## 当前完成门

1. Issue #96 的实现和 Windows stderr 回归测试完成。
2. `tests`、Parser Center CI、普通安全包、V3 安全部署包全部通过。
3. PR 合并到 `master`，确认 `master` 包含修复并清理临时分支。
4. master push 发布新的 verified V3 Release，metadata / manifest 包含 `winps51_native_process_stderr_safe=true`。
5. 生产机器从 6178 WebUI 再次执行一键升级；最终以当前生产提交切换到新 Release 目标并且服务验证通过为准。
