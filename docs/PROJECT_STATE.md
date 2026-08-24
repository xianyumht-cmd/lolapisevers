# Project state

更新时间：2026-08-25 +08:00

## Canonical development

- 默认开发分支：`master`；GitHub 中的实际 `master` 提交始终是开发状态的最终依据。
- Release 下载控制与服务重启验证改造记录：Issue #81 / PR #82。PR/Issue 是否已合并关闭以 GitHub 实时状态为准，本文不复制临时分支生命周期状态。
- PR #80 已建立 Release 多源测速、断点续传与实时进度的第一版基础。
- 当前收尾任务：Issue #83，统一 OP.GG 海符榜百分比字段并补全 detached 部署进程终态。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；代码开发、CI 和本地引导包生成不等于已执行生产部署。

## 已验证的问题

- 私有仓库 Release 的公共 GitHub 镜像通常无法读取私有资产，因此安全实现不会向第三方镜像发送 GitHub Token；实际可用下载源可能只剩 `github-api`。
- `requests` 的 read timeout 只能检测“完全没有数据”的停顿。极低速涓流仍可能持续返回少量数据，使旧下载器长时间保持 `downloading`。
- 旧下载器按 1 MiB chunk 更新进度，低速链路下 UI 很久不变化，进一步放大“卡死”观感。
- `update-state.json` 是持久化文件。服务重启后旧下载线程已经不存在，新 6178 仍可能把旧 `downloading` 状态显示成活任务。
- 原 WebUI 服务重启只安排 `Restart-Service` 后立即返回，没有验证 NSSM 服务 PID 是否真正更换；页面快速恢复本身不能证明是否发生过重启。
- OP.GG 海符榜的 `performance` / `popular` 上游值可能以 0~1 比例或 0~100 百分点两种形式出现；直接交给统一 `pct()` 会把 91.8 误显示为 9180%。
- detached Release 部署旧实现只记录 `Popen` 成功和 PID，不追踪外部 PowerShell 是否仍存活；外部进程在 `update.log` 初始化前退出时，WebUI 会永久停在 `scheduled / 独立部署进程已启动`。

## Issue #81 / PR #82 设计

- Release 更新改为进程内后台 worker；启动 POST 立即返回，WebUI 只轮询本地状态。
- active 状态记录 `worker_pid`、`run_id`、heartbeat；持久化 active 状态若不属于当前进程/没有存活 worker，转换为 `interrupted`，允许从 `.part` 继续。
- WebUI 提供暂停、继续、重新连接、清空断点重下四个控制。
- 下载 chunk 缩小到 64 KiB，并使用低速窗口熔断；默认连续约 30 秒低于 32 KiB/s 会断开当前连接并从断点重连，相关阈值可通过环境变量调整。
- 服务重启记录重启前 PID；后续 `/admin/service/status` 只有观察到 Running 且 PID 变化后才把本次重启标记为 `verified`。
- WebUI 重启按钮轮询验证结果，不再把“命令已安排”直接当成“重启成功”。

## Issue #83 设计

- OP.GG parser 在数据边界把 `performance` / `popular` 统一成 0~1：0.918 保持 0.918，91.8 / `91.8%` 转成 0.918；负数、非数、>100 的异常值丢弃为 `None`。
- 图片、JSON、排序和推荐方向继续只消费统一的 0~1 值，避免渲染层再猜单位。
- `scheduled` 不再是终态：状态查询会检查 detached 部署 PID 和当前生产 commit；PID 活着显示 `deploying`，PID 已退出且 commit 已切换则记 `complete`，PID 已退出且 commit 未切换则记 `failed`。
- detached PowerShell 标准输出/错误输出额外写入 `launch.log`；即使 `Start-Transcript` 尚未创建 `update.log` 就退出，也能保留启动期诊断。
- 外部 PowerShell 启动后 250ms 内立即退出会直接标记 `deployment_launch_failed`，不再向用户显示假成功。
- 进入新的成功/活动阶段会显式清除旧 `error`，防止出现“100% + 部署中 + 历史 ConnectTimeout”的矛盾状态。
- WebUI 在 `scheduled/deploying` 期间继续轮询并显示部署 PID、进程存活状态、`launch.log` / `update.log`，直到 complete 或 failed。

## 安全边界

- Release Token 不回显、不写源码，也不会发送给第三方镜像。
- 暂停/重连保留 `.part`；清空断点只允许删除 `%PROGRAMDATA%\LOLDataSystem\updates` 下与当前 V3 包名严格匹配的文件。
- detached 部署运行期间禁止通过 reset/reconnect 启动新的下载或删除已验证部署包。
- 完整 V3 ZIP 仍必须通过官方 metadata 指定的 SHA-256、路径安全检查和内嵌 manifest 安全标志后才能启动部署器。
- V3 部署器继续负责候选测试、生产备份、基线健康检查、切换、后置验证与失败自动回滚。

## 交付与生产衔接

- 每次候选必须经过全仓测试、Parser Center CI、普通安全部署包和 V3 安全部署包验证；以对应 PR 最新 head 的 CI 状态为准。
- 当前安装了旧下载器的生产环境，若无法可靠完成 GitHub Release 下载，应先使用同一候选 CI 生成并验证过的本地 V3 引导包升级下载器本身。
- 本地引导完成后，6178 遇到旧进程残留的 active `update-state.json` 会将其识别为 `interrupted`，而不是继续伪装成活下载；之后可在 WebUI 选择继续、重连或清空断点。
- 生产实际版本必须通过运行时 `/build-info`/WebUI 当前提交或等价运行证据确认，不能仅凭仓库 PR/Release 状态推断。
