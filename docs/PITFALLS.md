# PITFALLS

## 2026-08-31 — GroupGuard plugin execution time is not end-to-end send time

- **现象**：生产日志中的 `plugin_execution_result` 显示战绩/海符榜需要数秒，容易直接把时间归因于图片生成或 API 返回。
- **根因**：该事件在结构化交付结果准备完之后、`sendUnifiedCommandResponse` 之前记录；随后还会经过 `external_query` 发送队列、随机风控延迟、OneBot action 和 QQ 侧处理。
- **防止复发**：查询链路必须同时记录 API query/render/delivery-preparation 与 GroupGuard T0/T1/T2/T3/T4/T8/T9；端到端均值只使用带有效 `sent_at` 的发送事件，并单独报告随机延迟。

## 2026-08-31 — 图片 text/image 对照必须标记业务和渲染 cache 状态

- **现象**：一次战绩图片请求可能只有约 0.2s，另一次海符榜图片约 1.5s；若直接与某次文本请求比较，会得出“图片固定多几秒”的错误结论。
- **根因**：业务结果缓存、最终图片缓存、装饰资源缓存和背景刷新状态彼此独立；图片首次返回还可能是 placeholder/warming，前后 payload 或资源完整性也可能不同。
- **防止复发**：每次对照同时记录 source、业务 cache、final-image cache、asset completeness、PNG bytes、base64 chars 和阶段耗时；至少分别做 cold、warming、warm 三种样本，不能只比较两个总耗时。

## 2026-08-11 — OP.GG ARAM 平衡卡的实时 HTML 不能按单一展示形态解析

- **现象**：海符榜基础 ARAM 层在真实环境中把亚索显示为“完整平衡暂不可用”，而 OP.GG 当前实际有攻速 `+2.5%`；库奇能拿到平衡值但版本显示“未校验”。
- **根因**：OP.GG 的原始 HTML 与浏览器最终可见文本存在小差异。版本可能只出现为 `Ver:` / `Version:`；正负号和数值可能被标签/空白拆成 `+ 2.5%`。另外平衡卡附近可能混入广告或普通统计数字，不能把所有数字都当作未知平衡字段。
- **防止复发**：
  1. 版本提取同时兼容 `Patch`、`Ver`、`Version` 和中英文版本文本。
  2. 平衡数值允许符号与数字之间出现空白，并在输出前归一化。
  3. 完整性 fail-closed 只针对未识别的带符号 `+X/-X` 调整数值；普通无符号页面数字不能触发解析失败。
  4. 回归至少覆盖亚索（单个正向攻速）、库奇（承伤 + 冷却）、萨勒芬妮（多项持续 debuff）三类形态。
  5. 不能只依赖手写的理想化 fixture；真实页面验收仍是发布前必要步骤。

## 2026-08-19 — SO1 readiness 不能只检查持久化 Session 而不自愈

- **现象**：生产环境 `/health` 持续 `degraded`、`/readyz` 返回 503，但 MySQL 与 Chromium 都正常；SO1 `/user/me` 返回未认证。执行一次真实 `/cross_query` 后，现有查询链路自动登录成功，随后健康状态立即恢复 `ready=true`。
- **根因**：旧 `check_readiness()` 只验证持久化 Session，并把未认证统一归为 `session_expired_or_challenge`；真正的 `_login()` 只在业务查询路径执行。因此 SO1 服务端作废 Session 后，即使账号密码仍有效，服务也会一直降级到下一次业务查询恰好触发登录。
- **防止复发**：
  1. readiness 对缺失/失效 Session 使用单飞（single-flight）的受控自动恢复，健康状态不再依赖“碰巧来一次业务查询”。
  2. 先区分 `ERR_UNAUTHORIZED`/Session 失效与验证码、Cloudflare 等 challenge；检测到 challenge 时禁止自动登录，并进入冷却等待人工处理。
  3. 登录失败必须限频/冷却，避免高频 health 探测反复打登录接口触发风控；健康响应只暴露安全的 reason/error class，不暴露账号、密码、Cookie 或上游响应正文。
  4. 回归测试至少覆盖并发单飞、失败冷却、challenge 阻断、状态文件损坏、缺少凭据和 `ERR_UNAUTHORIZED` 精确分类。
  5. 生产验收应主动制造一个失效 Session，确认仅访问 health/readiness 即可安全自愈，无需再用虚假召唤师触发 `/cross_query`。

## 2026-08-20 — 从登录自启迁移到 NSSM 时必须退休旧 Startup 链

- **现象**：机器已经由 `LOLDataSystem` / NSSM 自动启动 `ops\run_service.ps1`，但用户 Startup 目录仍残留指向同一项目 `start_hidden.vbs` 的快捷方式。登录时旧链会再次执行 `start_hidden.vbs -> run_server.bat -> powershell -> run_service.ps1`，与正式服务形成第二条启动入口，可能造成 5001/6178 端口冲突、额外 PowerShell/Python 进程和误导性的 CPU/进程排查结果。
- **根因**：早期使用登录 Startup 隐藏启动，后续新增 `install_persistence.ps1` 创建 NSSM 服务和 KeepAlive 任务时，只增加了新持久化入口，没有把旧 Startup 入口纳入迁移/验收条件；文档还曾把 `run_server.bat` 写成“推荐统一入口”，与“正式长期运行只保留服务”相互矛盾。
- **防止复发**：
  1. 正式长期运行的唯一入口是 `LOLDataSystem`；`run_server.bat` / `start_hidden.vbs` 只允许临时手动调试。
  2. 持久化安装前检查是否存在非服务拥有的 `run_service.ps1` supervisor；发现时先报 PID 并停止迁移，不自动杀进程。
  3. 服务和 KeepAlive 建立并验证“恰好一个 service-owned supervisor”后，再扫描所有可见用户 Startup 与 Common Startup。
  4. 只处理明确指向当前项目 `start_hidden.vbs`、`run_server.bat` 或 `ops\run_service.ps1` 的启动项；命中项移动到 `logs\retired-startup\<时间戳>` 并保存 manifest，不直接删除。
  5. `health_check.ps1` 必须持续报告 supervisor 数量、父进程归属和旧 Startup 残留，避免端口正常就误判拓扑正常。
  6. 看到 PowerShell 每几秒在任务管理器排序中上浮时，先区分“同一常驻 PID 周期性活动”和“不断创建新 PID”；不能仅凭 `run_service.ps1` 的 5 秒轮询就断言它是高 CPU 根因。

## 2026-08-24 — Release 更新不能把持久化状态或“已安排重启”当成活性证据

- **现象**：Release 下载在 `github-api` 只有约 0.01 MB/s 时长期显示 `downloading`；服务重启后页面仍能读到旧的百分比并继续显示“升级中”。同时 WebUI 的“重启服务”在后台安排 `Restart-Service` 后立即提示成功，无法证明 NSSM 服务是否真的换过进程。
- **根因**：
  1. HTTP read timeout 只能发现一段时间完全无字节；持续涓流会一直续命。
  2. 旧下载器用 1 MiB chunk 才更新一次进度，低速链路下很久没有 UI 变化。
  3. `update-state.json` 是磁盘快照，不是 worker 存活证明；进程重启后快照仍保留 active 状态。
  4. 服务控制只证明“重启命令已启动”，没有记录并比较重启前后服务 PID。
- **防止复发**：
  1. 长任务状态必须同时携带进程内 worker 身份、`worker_pid`/`run_id` 和 heartbeat；新进程读到旧 active 状态时要自动降级为 `interrupted`，不能伪装成仍在执行。
  2. 网络下载采用小 chunk + 时间窗口吞吐判定；read timeout 之外必须有低速熔断，触发时保留 `.part` 并从断点重连。
  3. WebUI 的“暂停/继续/重连/重下”应是显式控制面，不使用“重启整个服务”代替下载控制。
  4. Windows 服务重启成功必须观察到 `Running` 且服务 PID 从旧值变为新值；页面是否很快恢复访问不能作为成功/失败判断。
  5. 任何“scheduled/accepted”类响应在 UI 中都只能显示为“已安排/等待验证”，不得直接显示为最终成功。

## 2026-08-25 — 第三方百分比字段必须在数据边界统一单位

- **现象**：OP.GG 海符榜实测图片出现 `9180%`、`9826%`、`684%` 等明显不可能的胜率/热度；同一份结构中上游实际值是 91.80、98.26、6.84。
- **根因**：`utils.formatters.pct()` 的契约是输入 0~1 比例并乘 100 输出百分号，而 OP.GG `performance` / `popular` 曾直接透传上游值；上游当前可能返回 0~100 百分点，也可能返回 0~1 比例，导致渲染层重复乘 100。
- **防止复发**：
  1. 外部来源的比例/百分比只能在 parser/service 边界做一次单位归一化，业务层和 renderer 不允许再猜单位。
  2. OP.GG 规则固定为：0~1 视为比例；大于 1 且不超过 100 视为百分点并除以 100；显式 `%` 字符串按百分点处理；负值、非有限数和 >100 视为异常数据。
  3. 排序、推荐、JSON 和图片必须共享同一个规范化字段，不能只在图片上临时 `/100`。
  4. 回归测试至少覆盖 `0.918`、`91.8`、`91.8%`、`6.84` 和非法值，最终通过统一 `pct()` 验证不会再输出 >100% 的误值。

## 2026-08-25 — detached 部署的 `Popen` 成功不是部署成功

- **现象**：83 MB Release ZIP 已下载到 100%，WebUI 显示 `scheduled / 独立部署进程已启动` 数分钟不变；staging 中有 ZIP、`extracted` 和 `Start-VerifiedReleaseUpdate.ps1`，却没有 `update.log`。生产 commit 仍停在旧版本。
- **根因**：旧状态机在 `subprocess.Popen()` 成功返回 PID 后立即把 `scheduled` 当作终态；worker 随后退出，WebUI 也停止轮询。它既不检查 detached PowerShell PID，也不检查生产 commit 是否切换；stdout/stderr 被送到 `DEVNULL`，所以 PowerShell 如果在 `Start-Transcript` 之前退出会完全没有诊断证据。
- **防止复发**：
  1. `scheduled` 只能是过渡态，后续 status 必须同时检查 detached PID 与当前生产 commit。
  2. PID 存活时显示 `deploying`；PID 退出且 commit 已切到目标才标记 `complete`；PID 退出且 commit 未切换必须标记 `failed`。
  3. 外部 PowerShell stdout/stderr 写入 staging `launch.log`，`update.log` 继续记录正式部署 transcript；启动前失败也必须可诊断。
  4. Popen 后短暂检查 `poll()`，立即退出直接记录 `deployment_launch_failed`，禁止展示“部署已启动”假成功。
  5. 部署阶段禁止 reset/reconnect 删除已验证包或启动第二条升级链；WebUI 必须继续轮询到明确的 complete/failed。
  6. 状态向前推进时必须清除历史 `error`，避免“100% + 部署中 + 旧 ConnectTimeout”同时出现。

## 2026-08-25 — Release 新旧关系不能只用 `target != current` 判断

- **现象**：生产已成功部署到 `3f209e...`，但 WebUI 仍把旧失败任务 `a446dab9...` 显示成“最新 Release / 可恢复目标”。实际上 `3f209e...` 是 `a446dab9...` 之后的前向提交，恢复旧任务会把生产代码降级。
- **根因**：controller 将 `failed` / resumable 状态视为本地短路状态，后续 status 不再查询 GitHub；同时更新判断只比较 SHA 是否不同，没有判断 Git 提交祖先关系，无法区分“目标比当前新”“目标比当前旧”和“双方已分叉”。
- **防止复发**：
  1. 持久化失败/中断状态只能作为历史或可恢复断点证据，不能永久覆盖空闲状态下重新获取的 `releases/latest`。
  2. 一键升级必须判断提交关系，而不是只判断 SHA 不同。对 GitHub Release 使用官方 Compare API：`current...target` 的 `ahead` 才是安全前向更新；`behind` 表示 Release 落后于当前，必须禁止降级；`diverged` 或无法确认时 fail-closed。
  3. 相同关系守卫必须覆盖 start、resume、reconnect、reset；不能只在前端禁用按钮，因为旧 API 调用仍可能启动任务。
  4. 活跃 worker / detached deploy 的进度轮询继续只读本地状态；空闲状态再刷新 GitHub，避免对活动任务引入竞态和额外网络请求。
  5. 手动检查空闲状态避免重复请求：一次 Release/metadata + 一次 compare 足够，不应先由旧 controller 请求一轮、guard 再请求一轮。
  6. 若无法证明 Release 是当前提交之后的前向目标，宁可显示“不可安全升级”也不能自动猜测或降级。

## 2026-08-25 — NSSM 服务中的 detached grandchild 不是可靠的部署所有权边界

- **现象**：状态机和 `launch.log` 都已补齐后，生产从 `4a4a210...` 在线升级 `02bf948e...`：83 MB ZIP 100% 下载并校验成功，但 `powershell.exe` PID 在真正创建 `update.log` 前退出；`launch.log` 文件由父进程创建成功却仍是空文件。
- **根因**：`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 只改变控制台/进程组语义，不等价于把进程生命周期转交给一个独立的系统托管者。在 NSSM/Windows 服务/作业对象环境中，grandchild 仍可能在 helper 获得稳定执行机会前消失。单纯“再多等几秒”或“再多重定向一个日志”不能解决进程所有权问题。
- **防止复发**：
  1. 会主动停止/替换自身宿主服务的部署器，必须由宿主进程树之外的稳定系统组件托管；Windows 使用 Task Scheduler/SYSTEM，而不是依赖 service child 的 DETACHED_PROCESS。
  2. 任务真正启动的证据必须是 helper 自己写出的 handshake/PID，而不是 `CreateProcess`、`schtasks /Run` 或任务注册命令返回 0。
  3. helper 在任何延时或正式部署前先写 `deployment.pid`，随后写 `launch.log` 首行；未出现握手应立即判定启动失败。
  4. Task Scheduler action 只引用已通过 SHA-256/manifest 校验的本地 staging helper，禁止把 GitHub Token、下载 URL 凭据或动态未校验脚本放进任务参数。
  5. 已完整校验的 V3 ZIP 与部署托管失败是两个不同层次；托管失败时应复用 staging，不得默认重新下载 80+ MiB 包。

## 2026-08-25 — 私有 Release 不能把“多加公共镜像”当成唯一提速方案

- **现象**：生产下载私有仓库 Release 时，多个公共 GitHub 加速前缀均探测失败，最终只能回退 `github-api`，实际吞吐降到十几 KB/s；继续机械增加公共代理并不能保证私有资产可读。
- **根因**：公共 GitHub 文件代理通常没有访问私有 Release 的仓库凭据。把私有 GitHub Token 拼进第三方代理 URL 虽可能绕过鉴权问题，却会把长期凭据暴露给不受信任的中间服务，安全代价不可接受。
- **防止复发**：
  1. 第三方镜像永远只做无凭据 best-effort 候选，失败就自动跳过，不能为提速向其发送 GitHub Token。
  2. 私有 Release 的认证只发生在 `api.github.com`；从官方 asset API 的 30x 响应取得 GitHub 自有 `release-assets.githubusercontent.com` / `objects.githubusercontent.com` 临时签名 URL。
  3. 临时签名 URL 只在当前进程内存使用，不写状态、日志、计划任务或外部镜像请求。
  4. 对 GitHub 官方签名 CDN 可使用受限并发 Range 提升吞吐；每段必须验证 206/Content-Range，失败时回退单连接断点续传。
  5. 无论下载源多快，最终完整性仍只由官方 metadata SHA-256 + safe extract + V3 manifest 决定，下载加速层没有权力降低发布安全门。

## 2026-08-28 — WinPS 5.1 不能用 `$ErrorActionPreference=Stop` 直接承接 Python/Node stderr

- **现象**：Release `lolapi-e0dbf15c15d2` 已下载并校验完成，Task Scheduler/SYSTEM 也正常启动部署器，但候选预检在生产切换前退出。Python 3.14 对测试源码的无效转义输出 `SyntaxWarning` 到 stderr，WinPS 5.1 将其变成终止错误；重复部署会在同一点失败。
- **根因**：V3 之前只把 Git 原生命令改成 `System.Diagnostics.Process` 捕获 stdout/stderr，候选阶段的 Python/Node 仍使用 `& $candidatePython ...` / `& $node.Source ...`。在 Windows PowerShell 5.1 的错误流语义下，“stderr 有内容”与“进程 ExitCode 非 0”不是同一件事，不能用 PowerShell ErrorRecord 代替原生进程退出码。
- **防止复发**：
  1. 部署关键路径的原生命令使用显式 process wrapper；stdout/stderr 作为诊断文本捕获，真实成功/失败只由进程 ExitCode 判定。
  2. wrapper 必须同时异步读取 stdout/stderr，避免大量 unittest/pip 输出造成管道死锁；非零 ExitCode 继续 fail-closed。
  3. Python 测试源码不得留下会在新 Python 版本升级成 `SyntaxWarning` 的无效转义；CI 增加全仓编译 warning 检查。
  4. V3 metadata/manifest 对这种兼容性使用独立安全标志，并在最终 ZIP 校验阶段确认 wrapper marker 存在、直接候选 Python/Node 调用不存在。
  5. 候选预检失败必须发生在停止生产服务之前；日志出现 `Production was not stopped or changed.` 时，不要把它误判为下载失败或生产半升级。

## 2026-08-28 — GroupGuard runtime 与 WebUI 不能各自实现配置优先级

- **现象**：121 的查询管理页把 `lol_battle` 显示为 `image`，同时页面底部显示默认 `forward`；真实战绩查询却出现 `forward_send_direct`。只读审计确认 `queryCommandProfiles.lol_battle.outputFormat="image"`、`global.lolQueryOutputFormat="forward"`，且测试群没有显式战绩输出覆盖。
- **根因**：WebUI `commandOut()` 已演进为优先展示 feature/profile 输出，而 runtime `resolveQueryOutputFormat()` 仍先读取已经合并后的 group/effective `lolQueryOutputFormat`。由于 effective group 对象会带入继承自 global 的 `forward`，runtime 无法区分“本群明确覆盖 forward”和“只是继承 global forward”，于是错误地让继承值遮住 profile `image`。同一配置契约在 WebUI 与 runtime 被分别实现，更新其中一侧后产生语义漂移。
- **防止复发**：
  1. 配置 key、默认值、可选值、归一化、继承和优先级属于一个跨 runtime/WebUI/API 的合同；修改任一项时必须在同一 task/PR 检查并同步所有受影响表面。
  2. 最终生效值必须区分 explicit group override 与 inherited/effective value；不能因为 resolved group 对象里存在字段就把它当成群覆盖。
  3. WebUI 的“最终/生效”预览优先消费服务端 canonical resolver 返回的 value + source；浏览器若自行推导，必须与 runtime 共用同一优先级并有 parity regression。
  4. 回归至少覆盖：global default、feature/profile、显式 group override、完全继承/无 override 四层，并断言 runtime delivery 与 WebUI/API preview 一致。
  5. 发现 drift 时修共享契约和测试，不能只改页面标签或只改 runtime 分支。Issue #98 跟踪当前查询输出优先级缺陷。
## 2026-08-31 — Do not infer image latency from a pre-queue plugin timestamp

- **现象**：插件执行时长或一次图片 API 耗时被误认为包含完整 QQ 发送链路。
- **根因**：旧 trace 没有标记入队、worker 获取和风控延迟，且 T8/T9 不在实际 OneBot action 边界。
- **防止复发**：跨仓库 trace 必须使用 T5/T6/T7/T8/T9 拆出队列等待、配置的风险延迟和 OneBot 处理；直接转发路径单独标记，不能伪造队列耗时。没有新的生产 trace 前不得改变延迟策略。
