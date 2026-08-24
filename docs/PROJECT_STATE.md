# Project state

更新时间：2026-08-24 +08:00

## Canonical development

- 默认开发分支：`master`
- 当前 `master` 基线：`7245238c22ae91f68068756516426a99b9e906cd`（PR #80，Release 多源测速、断点续传与实时进度）
- 当前任务：Issue #81「WebUI 升级任务控制、停滞恢复与服务重启验证」
- 当前任务分支：`fix/update-controls-restart-verify-20260824`
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；本任务不直接修改或重启生产。

## 已验证的问题

- 私有仓库 Release 的公共 GitHub 镜像通常无法读取私有资产，因此安全实现不会向第三方镜像发送 GitHub Token；实际可用下载源可能只剩 `github-api`。
- `requests` 的 read timeout 只能检测“完全没有数据”的停顿。极低速涓流仍可能持续返回少量数据，使旧下载器长时间保持 `downloading`。
- 旧下载器按 1 MiB chunk 更新进度，低速链路下 UI 很久不变化，进一步放大“卡死”观感。
- `update-state.json` 是持久化文件。服务重启后旧下载线程已经不存在，新 6178 仍可能把旧 `downloading` 状态显示成活任务。
- 原 WebUI 服务重启只安排 `Restart-Service` 后立即返回，没有验证 NSSM 服务 PID 是否真正更换；页面快速恢复本身不能证明是否发生过重启。

## Issue #81 目标设计

- Release 更新改为进程内后台 worker；启动 POST 立即返回，WebUI 只轮询本地状态。
- active 状态记录 `worker_pid`、`run_id`、heartbeat；持久化 active 状态若不属于当前进程/没有存活 worker，转换为 `interrupted`，允许从 `.part` 继续。
- WebUI 提供暂停、继续、重新连接、清空断点重下四个控制。
- 下载 chunk 缩小到 64 KiB，并使用低速窗口熔断；默认连续约 30 秒低于 32 KiB/s 会断开当前连接并从断点重连，相关阈值可通过环境变量调整。
- 服务重启记录重启前 PID；后续 `/admin/service/status` 只有观察到 Running 且 PID 变化后才把本次重启标记为 `verified`。
- WebUI 重启按钮轮询验证结果，不再把“命令已安排”直接当成“重启成功”。

## 安全边界

- Release Token 不回显、不写源码，也不会发送给第三方镜像。
- 暂停/重连保留 `.part`；清空断点只允许删除 `%PROGRAMDATA%\LOLDataSystem\updates` 下与当前 V3 包名严格匹配的文件。
- 完整 V3 ZIP 仍必须通过官方 metadata 指定的 SHA-256、路径安全检查和内嵌 manifest 安全标志后才能启动部署器。
- V3 部署器继续负责候选测试、生产备份、基线健康检查、切换、后置验证与失败自动回滚。

## 当前完成条件

1. Issue #81 实现和测试完成，UI/路由契约固定。
2. 全仓 CI、普通安全部署包和 V3 安全部署包全部通过。
3. PR 合并 `master`，确认 master 含新 worker/控制接口/PID 重启验证。
4. 更新本文件、`PITFALLS.md` 和 `OPERATIONS.md`。
5. 关闭 Issue #81；清理临时任务分支（若当前 GitHub 工具支持）。
6. 从 CI 验证通过的 V3 Artifact 生成 WinPS5.1 兼容本地引导包，让仍停留在旧下载器的生产环境先完成一次本地升级。
