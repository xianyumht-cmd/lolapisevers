# Project state

更新时间：2026-08-28 +08:00

## Canonical development

- 默认开发分支：`master`；**GitHub 实时 `master` 提交是开发状态最终依据，不在本文件中把某个 SHA 永久写成“当前 master”**，避免状态文档自身合并后立刻使该声明过期。
- 本轮规则变更前最后一个包含 runtime 代码的已验证基线为 `62097ddd262543c0d90af2ef95f048e7cefa23c2`；对应 verified Release 为 `lolapi-62097ddd2625`。
- PR #99 已合并，只修改仓库规则/知识文档，不改变 runtime 行为，也不需要为了本规则单独强制生产部署。最新 `master` / latest Release 仍应在执行任务时从 GitHub 实时核验。
- Issue #96 已关闭，PR #97 已合并；WinPS 5.1 原生命令 stderr 误杀候选测试的问题已进入上述 runtime 基线。
- PR #95 的查询图片延迟 P0 也已包含在上述 runtime 基线中。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；仓库改动、CI、Issue/PR 或本地诊断不等于已授权生产部署。

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