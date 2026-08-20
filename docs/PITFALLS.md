# PITFALLS

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
