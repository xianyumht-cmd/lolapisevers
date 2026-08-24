# Project state

更新时间：2026-08-25 +08:00

## Canonical development

- 默认开发分支：`master`；GitHub 中的实际 `master` 提交始终是开发状态的最终依据。
- Release 下载控制与服务重启验证改造记录：Issue #81 / PR #82。PR/Issue 是否已合并关闭以 GitHub 实时状态为准，本文不复制临时分支生命周期状态。
- PR #80 已建立 Release 多源测速、断点续传与实时进度的第一版基础。
- Issue #83 / PR #84 已完成 OP.GG 海符榜百分比字段统一与 detached 部署终态跟踪。
- Release freshness / 禁止降级保护记录：Issue #85 / PR #87；PR/Issue 生命周期状态以 GitHub 实时状态为准。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；代码开发、CI 和本地引导包生成不等于已执行生产部署。

## 已验证生产状态

- 2026-08-25 用户执行 PR #84 的 CI V3 本地引导包后，生产 `build-info` / Git HEAD 均为 `3f209e41243a920f0111d4a0f41470ed1cf22a8d`。
- 同次部署候选测试共 443 项通过；后置验证 `status=pass`，Windows 服务、`/livez`、MySQL、SO1 浏览器与会话、`/readyz`、build-info、分区/海符交付和 Git HEAD 均通过。
- 因 PR #84 是在 `a446dab9...` 之后的前向提交，生产 `3f209e...` 已包含旧 Release `a446dab9...` 的代码；任何把生产切回 `a446dab9...` 的动作都属于降级。

## 已验证的问题

- 私有仓库 Release 的公共 GitHub 镜像通常无法读取私有资产，因此安全实现不会向第三方镜像发送 GitHub Token；实际可用下载源可能只剩 `github-api`。
- `requests` 的 read timeout 只能检测“完全没有数据”的停顿。极低速涓流仍可能持续返回少量数据，使旧下载器长时间保持 `downloading`。
- 旧下载器按 1 MiB chunk 更新进度，低速链路下 UI 很久不变化，进一步放大“卡死”观感。
- `update-state.json` 是持久化文件。服务重启后旧下载线程已经不存在，新 6178 仍可能把旧 `downloading` 状态显示成活任务。
- 原 WebUI 服务重启只安排 `Restart-Service` 后立即返回，没有验证 NSSM 服务 PID 是否真正更换；页面快速恢复本身不能证明是否发生过重启。
- OP.GG 海符榜的 `performance` / `popular` 上游值可能以 0~1 比例或 0~100 百分点两种形式出现；直接交给统一 `pct()` 会把 91.8 误显示为 9180%。
- detached Release 部署旧实现只记录 `Popen` 成功和 PID，不追踪外部 PowerShell 是否仍存活；外部进程在 `update.log` 初始化前退出时，WebUI 会永久停在 `scheduled / 独立部署进程已启动`。
- PR #84 上线后进一步确认：controller 把持久化 `failed` / resumable 状态当作本地短路状态，会让旧任务 `a446dab9...` 长期遮挡 GitHub 最新 Release；同时仅比较 `target != current` 无法区分“前向更新”和“目标其实比当前旧”，存在误降级风险。

## Issue #81 / PR #82 设计

- Release 更新改为进程内后台 worker；启动 POST 立即返回，WebUI 只轮询本地状态。
- active 状态记录 `worker_pid`、`run_id`、heartbeat；持久化 active 状态若不属于当前进程/没有存活 worker，转换为 `interrupted`，允许从 `.part` 继续。
- WebUI 提供暂停、继续、重新连接、清空断点重下四个控制。
- 下载 chunk 缩小到 64 KiB，并使用低速窗口熔断；默认连续约 30 秒低于 32 KiB/s 会断开当前连接并从断点重连，相关阈值可通过环境变量调整。
- 服务重启记录重启前 PID；后续 `/admin/service/status` 只有观察到 Running 且 PID 变化后才把本次重启标记为 `verified`。
- WebUI 重启按钮轮询验证结果，不再把“命令已安排”直接当成“重启成功”。

## Issue #83 / PR #84 设计

- OP.GG parser 在数据边界把 `performance` / `popular` 统一成 0~1：0.918 保持 0.918，91.8 / `91.8%` 转成 0.918；负数、非数、>100 的异常值丢弃为 `None`。
- 图片、JSON、排序和推荐方向继续只消费统一的 0~1 值，避免渲染层再猜单位。
- `scheduled` 不再是终态：状态查询会检查 detached 部署 PID 和当前生产 commit；PID 活着显示 `deploying`，PID 已退出且 commit 已切换则记 `complete`，PID 已退出且 commit 未切换则记 `failed`。
- detached PowerShell 标准输出/错误输出额外写入 `launch.log`；即使 `Start-Transcript` 尚未创建 `update.log` 就退出，也能保留启动期诊断。
- 外部 PowerShell 启动后 250ms 内立即退出会直接标记 `deployment_launch_failed`，不再向用户显示假成功。
- 进入新的成功/活动阶段会显式清除旧 `error`，防止出现“100% + 部署中 + 历史 ConnectTimeout”的矛盾状态。
- WebUI 在 `scheduled/deploying` 期间继续轮询并显示部署 PID、进程存活状态、`launch.log` / `update.log`，直到 complete 或 failed。

## Issue #85 / PR #87 设计

- active worker 与 detached deploy 仍只读本地状态，避免进度轮询重复请求 GitHub。
- 空闲、失败、中断、已完成状态重新读取 GitHub `releases/latest`，旧 `update-state.json` 只作为 `last_update_state` 历史诊断，不再覆盖最新 Release。
- 使用 GitHub Compare API 对 `current...target` 做提交关系判定：`identical`=当前；`ahead`=目标在当前之后，可前向升级；`behind`=Release 落后于当前，禁止降级；`diverged`/无法确认=fail-closed，禁止升级。
- 当 Release 落后于当前时，页面返回 `available=false` 并明确说明“Release 尚未追上当前版本”；一键升级按钮不得启用。
- `start/resume/reconnect/reset` 进入控制器前复用同一关系守卫；旧断点目标落后、分叉或关系无法确认时不启动任务。
- 手动检查空闲状态只进行一次 Release/metadata 查询，再进行一次 GitHub compare；避免先由 controller 请求一次、guard 再重复请求一次。

## 安全边界

- Release Token 不回显、不写源码，也不会发送给第三方镜像；提交关系查询只发送到 GitHub 官方 API。
- 暂停/重连保留 `.part`；清空断点只允许删除 `%PROGRAMDATA%\LOLDataSystem\updates` 下与当前 V3 包名严格匹配的文件。
- detached 部署运行期间禁止通过 reset/reconnect 启动新的下载或删除已验证部署包。
- Release 目标若不能被证明是当前提交之后的安全前向提交，不允许启动下载/部署；宁可阻断也不自动降级或跨分叉部署。
- 完整 V3 ZIP 仍必须通过官方 metadata 指定的 SHA-256、路径安全检查和内嵌 manifest 安全标志后才能启动部署器。
- V3 部署器继续负责候选测试、生产备份、基线健康检查、切换、后置验证与失败自动回滚。

## 交付与生产衔接

- 每次候选必须经过全仓测试、Parser Center CI、普通安全部署包和 V3 安全部署包验证；以对应 PR 最新 head 的 CI 状态为准。
- 当前生产 `3f209e...` 已安全运行；在 Issue #85 修复进入生产前，不应使用旧页面的继续/重连/reset 去恢复 `a446dab9...` 任务。
- 安装 Issue #85 修复后，如果 GitHub 最新 Release 仍是 `a446dab9...`，页面应显示当前版本领先 Release 且禁止升级；当新 Release 目标位于 `3f209e...` 之后时才重新启用一键升级。
- 生产实际版本必须通过运行时 `/build-info`/WebUI 当前提交或等价运行证据确认，不能仅凭仓库 PR/Release 状态推断。
