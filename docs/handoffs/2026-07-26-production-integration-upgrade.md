# 2026-07-26 生产业务对接升级交接

> 状态：已部署并完成生产验收；发布门禁为 `partial`。核心查询、回调、构建追溯和凭据轮换均通过，蓝奏监控存量异常及人工入群命令验收仍待处理。

## 1. 发布范围

| 组件 | 生产位置 | 已部署提交 | 构建证据 | 契约/配置 |
|---|---|---|---|---|
| `lolapisevers` 与蓝奏监控 | `192.168.3.100`，端口 `5001`/`6178` | `bbc8ea2d2687820e4c4a3b400c7568a771f10519` | 源码清单 SHA-256 `e177a5948b953d12b92486739def48dad235e8c7bc1a1f2fe0cf9605dd161641`，54 个运行时文件 | `groupguard-lol-api.v2`，配置 schema 5 |
| `onebot-plugin-groupguard` | `192.168.3.89:/mnt/sda1/groupguard/app` | `d4cb5b7135fb30272ed60188d38e7fe0bbd566e8` | `snowluma-service.mjs` SHA-256 `778bea27b04ab6b9c2905780b515a52ef4509476fa553a863167db8da8f711a8`；发布包 SHA-256 `ebe5714ce289e302d2f66cd815fcd9f9254307976be7758e9abb71fa9af2b58e` | `groupguard-lol-api.v2`，配置 v8 |

主要升级包括：统一本地封号查询路由；修正管理端查询测试器；稳定事件 ID、逐目标回执和持久化幂等；拆分存活/就绪/构建信息；ARAM 缓存与条件请求；部署前校验、自动回滚及运行源码清单校验；移除硬编码生产地址并改用显式配置。

## 2. 生产验收

| 验收项 | 结果 | 已确认事实 |
|---|---|---|
| 服务存活与就绪 | 通过 | 主 API `/livez`、`/readyz` 均为 HTTP 200；GroupGuard `/api/health`、`/api/readyz` 均为 HTTP 200。 |
| GroupGuard 连接状态 | 通过 | OneBot `status=connected`、`connected=true`、`bot_id_present=true`、`adapter=snowluma-onebot`；`ready=true`、`messagingReady=true`。 |
| 封号查询 | 通过 | `2621735529` 返回 HTTP 200，状态为“封禁”，生产 provider 标识为 `production-1`；插件测试器最终 HTTP 200，`uses_local=true`、`parameter_matches=true`。 |
| 战绩查询 | 通过但需观察 | `ZCG烧火棍丘丘人#73557` 最终返回 HTTP 200 并进入缓存；期间上游曾短暂出现 3 次“未找到”HTTP 503；插件测试器最终 HTTP 200，参数契约正确。 |
| ARAM | 通过 | `Yasuo` JSON 为 10 行；PNG 为 163010 字节；存在 ETag；条件请求返回 HTTP 304，约 8 ms；插件测试器最终 HTTP 200。 |
| 蓝奏回调到测试群 | 通过 | 授权测试群 `805402626` 实际投递结果为 `complete`；同一事件重放被抑制；服务 `/notify/test` 两次均 HTTP 200；没有私聊目标。 |
| 交叉契约只读运行 | 部分通过 | `contracts-20260726100237415`：8 项通过，监控就绪失败，回调未运行。 |
| 交叉契约受控写运行 | 部分通过 | `contracts-20260726100350856`：9 项通过，监控就绪失败；回调完成且重复投递被抑制。 |
| 凭据轮换 | 通过 | 已失效旧凭据返回 HTTP 401，新运行时凭据返回 HTTP 200；新值仅存在于生产运行时的 root-only、权限 `0600` 环境文件中。 |
| GitHub CI | 通过 | 已部署实现提交 `bbc8ea2` 在 `lolapisevers` PR #7 上 1/1 通过；已部署实现提交 `d4cb5b7` 在 GroupGuard PR #6 上 4/4 通过。后续仅追加本交接文档；两个 PR 均保持 draft，未合并。 |

GroupGuard 当前总体状态为 `degraded`，但就绪和消息发送能力为真；唯一 warning 是 `monitor_not_ready`，来源是蓝奏监控的 4 个失败 watcher 和 10 个 orphan watcher。

## 3. 备份与回滚锚点

| 对象 | 回滚锚点 |
|---|---|
| 服务本地配置/状态 | 备份 ID `20260726-173856-integration-upgrade`；manifest SHA-256 `c714fd338339b3bdeb351fbcdaafff6b701d7fd339ece19442b16f0232f9c867`。 |
| GroupGuard 手工发布包 | `manual-20260726-174304-55e713cb.tgz`；SHA-256 `84039be2adb0e140621a40c86bf5fb1f16e308453a9b8e6eefcedaff77546c18`。 |
| GroupGuard 自动部署回滚目录 | `dist.backup-20260726-175417-f04fe197`。 |
| GroupGuard v8 前配置 | `config.json.pre-v8-20260726T095516Z`。 |

回滚顺序：先停止对应服务；校验备份哈希；恢复配置与运行产物；重新启动；依次验证 build-info、livez、readyz、OneBot 连接和测试群投递。不要跨版本只恢复配置或只恢复产物。

## 4. 已知限制

- `LIMIT-MONITOR-READINESS`：蓝奏监控 `/readyz` 仍为 HTTP 503，当前有 4 个 failed watcher 和 10 个 orphan watcher；运行循环正常，pending 为 0。
- `LIMIT-BATTLE-UPSTREAM`：战绩上游存在短暂“未找到”503，当前依靠成功结果缓存缓解。
- `LIMIT-HEALTH-DEGRADED`：GroupGuard 因 `monitor_not_ready` 显示 degraded，`updatePushReady=false`；实际 OneBot 连接、就绪及测试群出群链路均已验证。
- `LIMIT-CALLBACK-CRASH-WINDOW`：回调仍存在进程崩溃时的 at-least-once 小窗口。
- `LIMIT-MONITOR-SINGLETON`：同一 state 文件只支持单监控实例。
- `LIMIT-QUERY-UI`：管理界面的查询设置与实际运行设置仍有差异，ARAM 最明显。
- `LIMIT-CROSS-REPO-CI`：当前 mock CI 不是两个仓库真实组合部署测试。
- `LIMIT-LEGACY-TEXT`：存在与本次升级无关的历史乱码。
- `LIMIT-BAN-LKG`：封号服务的 last-known-good 缓存仅在内存中，重启后丢失。
- `LIMIT-INBOUND-COMMAND`：未由真实群成员生成“查封号 2621735529”和“查战绩 ZCG烧火棍丘丘人#73557”两条入群命令；原因是仅有生产机器人且忽略自身消息。命令适配器与实际出群链路已分别验证，不能将其等同于完整入群闭环。

## 5. 后续维护顺序

| 顺序 | Action ID | 动作 | 完成标准 |
|---:|---|---|---|
| 1 | `NEXT-MONITOR-FAILED` | 逐项诊断 4 个 failed watcher，区分上游故障、解析漂移和已失效配置。 | failed 降为 0，或每项都有经确认的停用/接受记录。 |
| 2 | `NEXT-MONITOR-ORPHAN` | 审核并归档/清理 10 个 orphan watcher，禁止直接删除未知状态。 | 配置 watcher 与 active state 一致，清理留有审计记录。 |
| 3 | `NEXT-BATTLE-STABILITY` | 为战绩上游短暂 503 增加稳定性统计和告警，复核缓存最大年龄。 | 连续观测窗口内成功率达到目标，503 可定位且用户提示真实。 |
| 4 | `NEXT-HUMAN-INBOUND` | 由真实成员在 `805402626` 发送两条指定查询命令。 | 每条命令只有一个最终回复；参数、来源、缓存/陈旧状态与实际契约一致。 |
| 5 | `NEXT-CALLBACK-DURABILITY` | 评估持久化 outbox/inbox 或事务性回执，关闭崩溃窗口。 | 崩溃恢复测试不丢消息，重复事件不重复出群。 |
| 6 | `NEXT-MONITOR-LOCK` | 增加 state 文件实例锁，或迁移到支持多实例的持久化存储。 | 第二实例无法误写同一 state，或多实例并发测试通过。 |
| 7 | `NEXT-QUERY-SETTINGS` | 统一管理界面、测试器与真实命令的配置来源，优先处理 ARAM。 | 页面展示值、测试请求与真实群命令使用同一适配器。 |
| 8 | `NEXT-CROSS-REPO-CI` | 建立固定版本的双仓契约集成 CI。 | CI 能构建两个真实提交并覆盖查询、回调、幂等和 readiness。 |
| 9 | `NEXT-LEGACY-TEXT` | 清理历史乱码并增加 UTF-8 往返测试。 | UI、日志和通知不存在替换字符或乱码回归。 |
| 10 | `NEXT-BAN-LKG` | 将封号 LKG 改为有最大年龄的持久化缓存。 | 重启后仍可受控降级，且过期数据不会伪装成实时结果。 |
| 11 | `NEXT-PR-REVIEW` | 人工审阅并决定是否将 PR #7、PR #6 从 draft 转为 ready/合并。 | CI 仍为绿色，PR 历史包含已部署提交且其后只有已审阅的交接文档，获得明确合并授权。 |

## 6. 安全与 Git 交接

- 本文不包含密码、回调凭据值、provider URL、GitHub 凭据或实际消息 ID。
- 旧回调凭据在 active app env、active 蓝奏配置、active state 及 88 个 runtime log 中的出现数均为 0。
- 已失效旧值仅保留在本地回滚备份中；相关 active 文件、3 个 app-env 自动备份和 3 个 config 自动备份均关闭 ACL 继承，仅允许 `Administrator`/`SYSTEM`。
- 服务仓已加入 `*.bak.*`、`*.bak-*`、`*.bad.*` 精确忽略规则，避免运行时备份误提交。
- 交接文档只应提交本文及同名 JSON；不得用宽泛 `git add .` 带入运行时备份、状态文件、构建目录或秘密。
- PR 地址：[lolapisevers #7](https://github.com/xianyumht-cmd/lolapisevers/pull/7)、[my-napcat-sys #6](https://github.com/xianyumht-cmd/my-napcat-sys/pull/6)。当前均为 draft，未授权合并。

审计来源：`docs/audits/2026-07-26-production-integration-audit.json`（SHA-256 `5650346076aa23be1474dd15327359a46e309ec21a16bb24ec4f0f4ef1719c58`）及同名 Markdown（SHA-256 `50b6913a75a5d1094b72b357f48bc0c4224f3ece7dd97dbfb569b8f33b683034`）。
