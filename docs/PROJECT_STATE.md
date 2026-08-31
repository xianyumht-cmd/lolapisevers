# Project state

更新时间：2026-08-31 +08:00

## Canonical development

- 默认开发分支：`master`；**GitHub 实时 `master` 提交是开发状态最终依据，不在本文件中把某个 SHA 永久写成“当前 master”**，避免状态文档自身合并后立刻使该声明过期。
- 本轮规则变更前最后一个包含 runtime 代码的已验证基线为 `62097ddd262543c0d90af2ef95f048e7cefa23c2`；对应 verified Release 为 `lolapi-62097ddd2625`。
- PR #99 已合并，只修改仓库规则/知识文档，不改变 runtime 行为，也不需要为了本规则单独强制生产部署。最新 `master` / latest Release 仍应在执行任务时从 GitHub 实时核验。
- Issue #96 已关闭，PR #97 已合并；WinPS 5.1 原生命令 stderr 误杀候选测试的问题已进入上述 runtime 基线。
- PR #95 的查询图片延迟 P0 也已包含在上述 runtime 基线中。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；仓库改动、CI、Issue/PR 或本地诊断不等于已授权生产部署。

## 2026-08-31 已核验：生产查询链路与图片时延边界

本节记录的是 2026-08-31 对实际运行主机的只读核验，不是根据目录名或分支名推断的拓扑。

- `192.168.3.121` 是生产机器人主机：`groupguard-snowluma` 使用 host network，GroupGuard 编译版本为 `23ed0084eb2214e591a0108b5b82d33fb10b00ba`；SnowLuma 的 OneBot HTTP/WS 端口分别为 3000/3001。
- 121 上没有 5001/6178 监听。GroupGuard 的 `lolApiBaseUrl` 指向 `http://192.168.3.100:5001`，因此查询 API 生产端在 100，不在 121。
- `192.168.3.100` 的 `LOLDataSystem` Windows 服务由 NSSM 托管 `ops\\run_service.ps1`，运行 `.venv\\Scripts\\python.exe app.py`；5001 是查询 API，6178 是控制/更新 API。当前 API 运行版本为 `62097ddd262543c0d90af2ef95f048e7cefa23c2`，合同为 `groupguard-lol-api.v2`。
- 活跃查询路径是：GroupGuard 动态 intranet 插件 → `POST /api/v1/groupguard/query` → 100 上的查询/渲染 → JSON 交付包 → GroupGuard 把图片转为 `base64://...` → external_query 发送队列 → SnowLuma OneBot WS → QQ。API 不返回公共图片 URL，也不要求 GroupGuard 再下载图片。
- 121 当前查询 profile 对战绩、海符榜均偏好 image；发送队列为分群模式、并发 2，`external_query` 未配置专属风控延迟，因而继承全局随机延迟 500–1500ms。
- API 健康检查可用；LOL Ban provider 当前为 degraded（有历史缓存但最近成功数为 0），这是另一条链路，不作为战绩/海符榜图片时延根因。

### 实测边界（121 直连 100，未触发 QQ 发送）

| 请求 | API 总耗时 | 返回体/图片体积 | 观察 |
| --- | ---: | ---: | --- |
| 战绩 text | 5.14s | 1.7KB | 当次业务数据为 live，冷查询明显变慢 |
| 战绩 image（首次对照） | 0.21s | JSON 506KB，PNG 379KB | 业务结果命中 cache，图片返回很快 |
| 战绩 image（再次） | 0.09s | JSON 506KB，PNG 379KB | 最终图片 cache 命中 |
| 海符榜 text | 1.97s | 2.3KB | OP.GG 业务数据返回 |
| 海符榜 image（首次对照） | 1.51s | JSON 238KB，PNG 178KB | 受到业务/装饰资源/图片 cache 状态影响 |
| 海符榜 image（再次） | 0.16s | JSON 239KB，PNG 179KB | warm 后显著下降，且前后图片 hash 不同，不能当作严格 cold/warm 同 payload 对照 |

这些数字证明 121→100 的连接不是秒级瓶颈，也不能证明“图片编码固定多 6 秒”。生产 GroupGuard 的历史插件耗时均值为：战绩约 6.59s、海符榜约 8.67s、ARAM 约 4.62s；该指标在结构化交付包返回前记录，**不包含后续发送队列**。生产 `bot_send_events` 近 24 小时的已发送 `external_query` 图片消息 332 条，入队到 OneBot 返回平均约 2.78s，其中随机延迟平均约 1.03s，剩余约 1.75s 由队列等待与 OneBot 处理共同构成。失败消息没有有效 `sent_at`，不纳入该均值。

当前最可靠的根因判断是：业务上游冷查询是插件耗时的主要来源；图片发送还叠加了 500–1500ms 随机延迟、并发为 2 的发送队列和 OneBot 处理时间。API 已有图片/装饰资源优化，但此前缺少跨 API、解码、入队、发送完成的同一条 trace，因此不能把 base64、PNG 编码、OneBot 上传或 QQ 网络中的任何一项单独定性为“6 秒根因”。

### 本轮执行状态

- 已在最新 `origin/master` 上创建后续观测分支，补充 API 查询、图片缓存/装饰资源/PNG 编码、交付准备阶段计时；GroupGuard 源码侧已补齐 T0-T9 队列/风控/OneBot trace，并保留原有交付合同。直接转发路径继续记录 T8/T9，不伪造队列时间戳。
- 计时只记录阶段、耗时、图片字节数/编码字符数、缓存状态和尺寸，不记录账号、群号、Cookie、Token 或原始查询内容。
- 本地验证已完成：Python unittest `476` 项通过；GroupGuard typecheck、全量 npm test、`build:all`、独立 `build:snowluma`、不可变部署包预检均通过。GroupGuard 分支提交为 `a61f2bf87a22276e664a2ab83d65c7061454bfd8`，lolapisevers 文档分支提交为 `0849ccbe4d07e42831a05bf96d01c2c2d4ef853d`。
- PR #101（lolapisevers）与 GroupGuard PR #56 已创建，均保持 open、未合并。对应 GitHub Actions 运行在作业启动前以 `startup_failure` 结束，页面提示疑似 workflow file issue；当前没有可下载的失败作业日志，也不能重跑，因此 CI 结论暂记为 blocked，而不是代码测试失败。
- 未重启、未部署、未修改 121 或 100 的生产文件。下一步是先恢复/确认 CI 工作流可启动并取得 PR checks；之后仍需按每个 PR 单独批准，再决定是否进入生产部署。

## 2026-08-31 follow-up: exact image stages and bounded optimization

- Local deterministic renderer baselines were measured before this follow-up:
  battle cold render was about 120 ms with synthetic complete assets, ARAM
  cold render about 70 ms, and final-image cache hits about 0.1–0.2 ms. A
  379 KB PNG base64 encoding sample took about 1.5 ms. These are local
  renderer/encoding measurements, not QQ delivery measurements.
- The API now exposes monotonic-relative image stage offsets for T3 render
  start, T4 render finish, T5 asset lookup start, T6 asset availability and
  T7 API payload preparation/availability. GroupGuard additionally uses
  `performance.now()` for elapsed T0–T9 calculations and records T7 plugin
  payload preparation immediately before OneBot plan conversion.
- The only behavior optimization in this follow-up is an ARAM image cache-hit
  fast path when both `aram_balance:<alias>` and
  `aram_base_balance:<alias>` are already present in the existing TTL cache.
  It avoids repeated champion lookup work, preserves the same cached values
  and TTL, and falls back unchanged when either layer is absent.
- No queue, risk delay, retry policy, image transport contract, production
  configuration, service, container, or runtime data was changed.

## 2026-08-31 post-push verification

- Follow-up commit `bcac8a70ea841cd2ed481d85a425d9552252fc1a` is pushed to
  `codex/image-delivery-observability-20260831`; PR #101 remains open and
  unmerged. Local full regression completed with 477 tests passing.
- A paired PR watcher attempt could not refresh the GitHub GraphQL state because
  the API returned `EOF`; this is an external observation failure, not a source
  test failure. No merge or production action was taken.

## 当前开放问题：GroupGuard runtime / WebUI 配置语义漂移（Issue #98）

2026-08-28 对 `192.168.3.121` 的 `groupguard-snowluma` 做只读审计后，确认查询输出配置存在 runtime / WebUI 优先级不一致：

- `global.lolQueryOutputFormat="forward"`。
- `queryCommandProfiles.lol_battle.outputFormat="image"`。
- WebUI 查询管理页优先展示 feature/profile，因此战绩显示 `image`。
- runtime `resolveQueryOutputFormat()` 先读取 resolved/effective group 的 `lolQueryOutputFormat`；继承自 global 的 `forward` 会被当成群值并遮住 profile `image`。
- 真实战绩日志出现 `forward_send_direct`，证明这不是单纯页面文案问题。
- 当前 `config.json` 的 `groups` 为空，但 SQLite `group_config` 有 16 条持久化分群配置；判断群覆盖必须同时看 runtime storage，不能只看主 JSON。

这属于配置合同漂移，不应通过强制覆盖生产配置来规避。Issue #98 的修复方向是建立一套 canonical precedence，并让 runtime、WebUI effective preview、WebUI save/API 和回归测试共用同一语义。

## 已确认属于预期设计、不是缺陷

- 121 自撤回开启：约 50% 概率、10–30 秒随机撤回，用于风控。
- `global.outputLocale="en"` 是当前预期输出语言。
- 121 全局问答关闭、查询开启符合当前查询机器人分工。

## 其他现场观察（未在本规则任务中修改）

- 当前启动日志仍出现 OneBot `send_group_msg` 被拒绝（`result=120`）的发送失败；有战绩请求已走到图片消息阶段后被 OneBot 拒绝。这与 Issue #98 的输出优先级问题是不同层次。
- 动态命令校验日志曾发现旧 HTTP Provider/参数映射错误；应作为独立后续问题处理，避免与配置优先级修复混在同一个改动里。
- 部分 SQLite 分群记录保存的是历史整份配置快照，部分只保存小范围覆盖；后续若做配置清理，必须保留真正有意的群级差异，不能直接批量删除。

## Durable prevention

PR #99 已把“runtime / WebUI 配置同步”升级为仓库级强制要求：

- 任一配置 key、默认值、可选值、归一化、继承/优先级或配置驱动的 runtime 行为发生变化时，必须在同一 task/PR 检查并同步 runtime、WebUI display/effective preview、WebUI edit/save、API、docs 和 tests。
- WebUI 若声称展示“最终/生效”值，不得使用与 runtime 不同的优先级；优先返回 canonical value + source。
- 配置行为回归必须覆盖相关的 global、profile/feature、explicit group override、inherited/no-override 层，并验证 runtime 与控制面一致。

## Next actions

1. 按 Issue #98 修复 GroupGuard 查询输出 precedence，先用测试定义 canonical contract，再同步 runtime + WebUI/API；不要先强制改生产配置。
2. #98 独立完成并验证后，再分别处理 OneBot `result=120` 和动态命令加载错误。
3. 若后续整理 16 条分群配置，先生成只读差异报告，区分 intentional override 与历史快照，再决定是否压缩覆盖。
