# lolapisevers 全仓 Bug 清单（2026-08-01）

审查结论：**本次基线共登记 37 项问题，全部标记为 `OPEN`：P1 10 项、P2 21 项、P3 6 项。**

机器事实源：[2026-08-01-full-bug-inventory.json](./2026-08-01-full-bug-inventory.json)。

## 审查基线

- 仓库：`xianyumht-cmd/lolapisevers`
- 分支：`master`
- SHA：`35b258af431cf6117f80138147500eeb24059b0a`
- 审计分支：`audit/full-bug-inventory-20260801`
- PR：`#27`
- 范围：主 API、查询协议和官方客户端、蓝奏监控/WebUI、SQLite/MySQL、上游 HTTP、PowerShell 运维、依赖与测试。

> 这里的“全仓”指本次基线、静态检查、跨文件调用链和最小复现能够识别的全部问题，不是对未来代码或不可达生产环境绝对无其他缺陷的证明。

## 审计结果

| 检查 | 结果 |
|---|---|
| Linux 单元测试 | 227 通过，2 跳过 |
| Windows 单元测试 | 227 通过 |
| Python compileall | 通过 |
| 全仓 PowerShell 语法 | 通过 |
| 生成后的 WebUI JavaScript | 通过 |
| Ruff / Bandit | 已人工复核并剔除误报 |
| pip-audit | 失败：5 个包、31 个唯一公告 |

现有测试全部通过，但没有覆盖并发不同参数、旧路由兼容、跨端大小限制、匿名写入和部署失败回滚等场景。

## 总览

| ID | 级别 | 状态 | 问题 | 批次 |
|---|---:|---|---|---:|
| `GG-001` | **P1** | 已确认 | 不同账号的并发风险查询会共享同一上游结果 | 1 |
| `LZ-001` | **P1** | 已确认 | 蓝奏测试推送按钮和新路由同时失效 | 1 |
| `GG-002` | **P1** | 已确认 | 举报幂等键冲突时未校验原请求内容 | 1 |
| `GG-003` | **P2** | 已确认 | 官方举报客户端会为缺失的幂等键自动生成新 UUID | 2 |
| `GG-004` | **P2** | 已确认 | 请求 ID 的有损清洗会把不同 ID 合并 | 2 |
| `GG-005` | **P2** | 已确认 | 官方客户端拒绝服务端明确支持的功能别名 | 2 |
| `GG-006` | **P1** | 已确认 | 合并转发超过 32 节点时静默截断内容 | 1 |
| `GG-007` | **P1** | 已确认 | 服务端能生成官方客户端必然拒绝的合法响应 | 1 |
| `GG-008` | **P2** | 已确认 | 客户端在完整下载响应后才检查 16 MiB 上限 | 2 |
| `CR-001` | **P2** | 已确认 | 只读查询会刷新记录 updated_at | 2 |
| `DYN-001` | **P1** | 已确认 | 动态 Provider 的 SSRF 校验可被重定向和 DNS 重绑定绕过 | 1 |
| `WEB-001` | **P1** | 已确认 | 举报写接口默认向局域网开放且没有鉴权 | 1 |
| `WEB-002` | **P2** | 已确认 | SO1 人工会话初始化接口默认无鉴权 | 2 |
| `WEB-003` | **P2** | 已确认 | 多个上游响应在内存中无上限读取 | 2 |
| `SEC-001` | **P2** | 已确认 | 授权失败审计日志无轮转且读取时全量载入 | 2 |
| `DEP-001` | **P1** | 依赖漏洞 | 锁定依赖版本命中 31 个唯一安全公告 | 1 |
| `SO1-001` | **P2** | 高概率 | 响应回调闭包可能跨重试写入下一轮状态 | 2 |
| `SO1-002` | **P2** | 已确认 | So1Client 单例会忽略后续配置并复用旧事件循环对象 | 2 |
| `HLTH-001` | **P2** | 已确认 | SO1 readiness 只检查浏览器连接，不检查登录会话 | 2 |
| `HLTH-002` | **P2** | 设计风险 | 全局 readiness 将互不相关功能硬绑定到 MySQL 和 SO1 | 2 |
| `LZ-002` | **P2** | 已确认 | 配置加载路径未拒绝空或重复 watcher ID | 2 |
| `LZ-003` | **P3** | 已确认 | scan_on_start=false 时服务可能长期保持 never_scanned 降级 | 3 |
| `LZ-004` | **P3** | 已确认 | WebUI 配置更新使用宽松布尔和方法解析 | 3 |
| `LZ-005` | **P2** | 高概率 | 热更新同 ID watcher 时未与正在执行的旧扫描串行化 | 2 |
| `LZ-006` | **P3** | 设计风险 | 没有启用通知目标时变化会永久保持 pending | 3 |
| `PROV-001` | **P2** | 高概率 | WER 递归提取器可能把容器对象当成文件 | 2 |
| `XQ-001` | **P2** | 高概率 | Riot ID 查询失败后按纯名称回退可能返回错误玩家 | 2 |
| `ADMIN-001` | **P2** | 已确认 | 诊断逻辑硬编码端口、Windows 路径和服务语义 | 2 |
| `ADMIN-002` | **P2** | 已确认 | 配置管理 token 后，内置 API 调试器无法调用受保护的蓝奏接口 | 2 |
| `API-001` | **P2** | 已确认 | 非法蓝奏配置更新返回 500 而不是客户端错误 | 2 |
| `OPS-001` | **P1** | 已确认 | 正式接管脚本可能强制结束其他项目的 app.py 进程 | 1 |
| `OPS-002` | **P1** | 已确认 | 持久化安装在验证新服务前先删除现有服务 | 1 |
| `OPS-003` | **P2** | 已确认 | NSSM 下载后未做完整性验证即以管理员权限执行 | 2 |
| `OPS-004` | **P2** | 已确认 | 健康检查和接管失败日志仍读取过期文件名 | 2 |
| `CFG-001` | **P3** | 已确认 | 核心整数环境变量缺少安全解析和范围校验 | 3 |
| `DB-001` | **P3** | 已确认 | 数据库名和字符集被直接插入 CREATE DATABASE SQL | 3 |
| `SEC-002` | **P3** | 条件风险 | 未配置 token 时的 loopback 信任在本地反向代理后会失效 | 3 |

## 详细登记

### GG-001 · P1 · 已确认：不同账号的并发风险查询会共享同一上游结果

- 状态：`OPEN`；组件：`contact-risk/upstream`；位置：`services/upstream_http_client.py:151,263-273`；`services/contact_risk_service.py:203-219`
- 证据与影响：UpstreamHttpClient 的 singleflight 仅以 source_id 作为键；风险查询的 source_id 仅由 Provider 名称生成，不含 QQ、微信号或最终 URL。最小复现中同时查询 11111 和 22222 只发出一次网络请求，第二个请求收到第一个账号的结果。 会把 A 账号的骗子/同行结果返回给 B 账号，造成错误风控判断，并形成跨账号数据泄露。
- 修复与验收：singleflight 键必须包含请求方法、规范化 URL、请求体和影响响应的头；至少把标识符摘要加入 source_id。 回归测试：并发请求同一 Provider、不同 QQ/微信号，断言产生两次独立上游调用且结果不串号。
- 计划：`BATCH-1`

### LZ-001 · P1 · 已确认：蓝奏测试推送按钮和新路由同时失效

- 状态：`OPEN`；组件：`lanzou-webui`；位置：`lanzou_update_push_api_server/server.py:268-278`；`lanzou_update_push_api_server/ui.py:132`；`lanzou_update_push_api_server/ui_control.py:143`；`lanzou_update_push_api_server/monitor.py:1080-1135`
- 证据与影响：当前两个 WebUI 都调用 POST /notify/test，但服务器已删除该路由并改为 /test-push，因此按钮返回 404；新的 /test-push 又调用不存在的 service.notifier.send，而 LanzouMonitorService 实际提供的是 send_test_event。 WebUI 的测试推送功能完全不可用；直接调用新路由会触发 500。
- 修复与验收：恢复 /notify/test 兼容路由并调用 service.send_test_event(watcher_id)；/test-push 如需保留应作为同一服务函数的别名。 回归测试：对两个路由做 TestClient 验证，并执行生成后的 WebUI 点击链契约测试。
- 计划：`BATCH-1`

### GG-002 · P1 · 已确认：举报幂等键冲突时未校验原请求内容

- 状态：`OPEN`；组件：`contact-risk/store`；位置：`services/contact_risk_store.py:68-77,138-176`
- 证据与影响：contact_risk_report_events 仅以 request_id 为主键。命中重复 ID 后只确认 ID 存在，再按当前请求目标读取风险记录，没有比对 category、identifier_type、identifier_value、content_sha256 或 source。最小复现中同一 request_id 用于不同账号，第二次被当作重复成功。 客户端或攻击者可通过碰撞 request_id 静默丢弃合法举报，并收到与原请求不一致的成功响应。
- 修复与验收：幂等事件必须保存并校验完整规范化请求指纹；只有完全相同才返回 duplicate，不同负载复用同一键应返回 409。 回归测试：同一 request_id + 相同负载返回 duplicate；同一 request_id + 不同账号/内容返回 409 且不修改记录。
- 计划：`BATCH-1`

### GG-003 · P2 · 已确认：官方举报客户端会为缺失的幂等键自动生成新 UUID

- 状态：`OPEN`；组件：`official-client/report`；位置：`clients/channel_neutral_query_client.py:66-69,294-320`
- 证据与影响：report(request_id='') 最终调用 _safe_request_id，空值会生成 UUID。调用方重试同一举报但没有稳定保存 ID 时，每次都会成为新请求。 网络重试、进程重启或调用方遗漏参数时可能重复计数；服务端的“必须提供 request_id”门禁被官方客户端绕过。
- 修复与验收：举报路径必须拒绝空 request_id；仅普通查询可以自动生成追踪 ID。 回归测试：report(request_id='') 必须抛出 report_request_id_required。
- 计划：`BATCH-2`

### GG-004 · P2 · 已确认：请求 ID 的有损清洗会把不同 ID 合并

- 状态：`OPEN`；组件：`delivery-protocol`；位置：`services/query_delivery.py:22-24`；`clients/channel_neutral_query_client.py:66-69`
- 证据与影响：服务端和客户端都把不允许字符替换为 '-' 并截断到 128 字符。最小复现中 'a b' 与 'a@b' 均变成 'a-b'。 追踪 ID 会错误归并；用于举报时可造成错误幂等、合法请求被抑制或审计串单。
- 修复与验收：不要有损改写幂等键；对不合法格式直接拒绝，或对原始值做带版本前缀的完整哈希。 回归测试：验证不同原始 ID 不会得到同一幂等键，并覆盖超长 ID。
- 计划：`BATCH-2`

### GG-005 · P2 · 已确认：官方客户端拒绝服务端明确支持的功能别名

- 状态：`OPEN`；组件：`official-client/protocol`；位置：`routers/groupguard_delivery.py:45-91`；`clients/channel_neutral_query_client.py:174-181,260-292`
- 证据与影响：服务端会把 ban、查封号等别名规范为 lolban 并在响应中返回 canonical feature；客户端却要求响应 feature 与原请求字符串完全相等。最小复现使用 ban 得到 feature_mismatch。 官方参考客户端与正式服务端契约不兼容，别名和大小写输入会出现假失败。
- 修复与验收：共享 canonicalize_feature 实现，或客户端只允许 canonical feature 并在发送前拒绝别名。 回归测试：对所有文档化别名做服务端+客户端 round-trip。
- 计划：`BATCH-2`

### GG-006 · P1 · 已确认：合并转发超过 32 节点时静默截断内容

- 状态：`OPEN`；组件：`delivery/forward`；位置：`services/query_delivery.py:132-151`
- 证据与影响：split_forward_text 最后直接返回 chunks[:MAX_FORWARD_NODES]，没有报错、截断标志或剩余分页。最小复现 140000 字符返回 128000 字符，丢失 12000 字符。 长查询、举报详情或动态接口结果会在用户不知情的情况下缺失尾部内容。
- 修复与验收：超限时明确失败、分页或改为文件附件；若必须截断，响应必须包含 truncation 元数据和可见提示。 回归测试：构造 33 个以上节点，断言不发生无标志的数据丢失。
- 计划：`BATCH-1`

### GG-007 · P1 · 已确认：服务端能生成官方客户端必然拒绝的合法响应

- 状态：`OPEN`；组件：`delivery/limits`；位置：`services/query_delivery.py:154-188`；`clients/channel_neutral_query_client.py:111-142`；`contracts/groupguard-query-delivery.v1.schema.json`
- 证据与影响：服务端 text_delivery/image_delivery 不执行客户端上限。最小复现中服务端生成的 13 MiB 图片被客户端以 invalid_delivery 拒绝；20001 字符文本同样被拒绝。JSON Schema 也未表达这些限制。 生产接口可返回 HTTP 200 + ok=true，但所有官方消费者都无法发送，形成协议级假成功。
- 修复与验收：把文本、图片、Base64、节点和总响应上限定义在共享协议模块与 Schema 中，并在服务端生成前强制执行。 回归测试：边界值与超限值都做服务端生成、Schema 校验、官方客户端解析三方契约测试。
- 计划：`BATCH-1`

### GG-008 · P2 · 已确认：客户端在完整下载响应后才检查 16 MiB 上限

- 状态：`OPEN`；组件：`official-client/http`；位置：`clients/channel_neutral_query_client.py:231-258`
- 证据与影响：_post 访问 response.content 后才判断长度；requests 在此之前已经将整个响应读入内存。 响应大小限制不能阻止内存耗尽，恶意或异常服务端可返回超大体积导致客户端进程高内存或崩溃。
- 修复与验收：使用 stream=True，先检查 Content-Length，再按块读取并在达到上限时立即中止。 回归测试：模拟无 Content-Length 的超大流和伪造 Content-Length，验证读取被硬上限终止。
- 计划：`BATCH-2`

### CR-001 · P2 · 已确认：只读查询会刷新记录 updated_at

- 状态：`OPEN`；组件：`contact-risk/store`；位置：`services/contact_risk_store.py:107-136`
- 证据与影响：get(touch=True) 同时更新 last_checked_at 和 updated_at。最小复现表明一次读取后 updated_at 改变。 最后修改时间不再代表举报数据变化，排序、清理、同步和审计会把“被查询”误认为“内容更新”。
- 修复与验收：读取只更新 last_checked_at；updated_at 仅在风险记录内容发生变化时写入。 回归测试：读取前后 updated_at 不变，last_checked_at 增加。
- 计划：`BATCH-2`

### DYN-001 · P1 · 已确认：动态 Provider 的 SSRF 校验可被重定向和 DNS 重绑定绕过

- 状态：`OPEN`；组件：`dynamic-query/security`；位置：`services/dynamic_query_service.py:241-264,320-373`
- 证据与影响：代码只在请求前解析并校验原始目标；requests 默认跟随重定向，跳转后的每一跳没有重新校验。DNS 在校验和实际连接时也会再次解析，存在 TOCTOU。 可配置或被接管的公网 Provider 能把服务重定向到 localhost、内网管理接口或云元数据地址。
- 修复与验收：禁用自动重定向或逐跳校验 Location；使用安全的地址固定方案并保持正确 SNI/Host，同时防止 DNS rebinding。 回归测试：覆盖 public→127.0.0.1、public→RFC1918 重定向，以及前后解析结果变化。
- 计划：`BATCH-1`

### WEB-001 · P1 · 已确认：举报写接口默认向局域网开放且没有鉴权

- 状态：`OPEN`；组件：`main-api/security`；位置：`core/config.py:35-39`；`app.py:19-48`；`routers/groupguard_delivery.py:408-485`
- 证据与影响：主 API 默认 APP_HOST=0.0.0.0，应用没有认证中间件；POST /api/v1/groupguard/report 可直接写 contact_risk.db。官方客户端限制的是目标地址，不是调用者身份。 同一局域网任何主机都可伪造骗子/同行举报，污染机器人查询结果和本地审计数据。
- 修复与验收：为跨仓写请求增加 HMAC、短期 token、mTLS 或受信反向代理鉴权，并加入主体审计和速率限制。 回归测试：无凭据、错误凭据、重放请求均被拒绝；合法签名成功且主体写入审计。
- 计划：`BATCH-1`

### WEB-002 · P2 · 已确认：SO1 人工会话初始化接口默认无鉴权

- 状态：`OPEN`；组件：`main-api/security`；位置：`routers/cross_session.py:12-29`；`core/config.py:35-39`；`app.py:19-48`
- 证据与影响：POST /cross_session_init 可触发最长 600 秒的可视浏览器人工登录流程，主 API 默认监听 0.0.0.0，路由没有管理员鉴权或限流。 局域网客户端可反复占用人工登录锁、弹出浏览器窗口并消耗资源，干扰正常战绩查询。
- 修复与验收：移入受保护的管理平面，要求管理员 token，并设置并发、冷却和审计。 回归测试：匿名调用返回 401/403；重复调用受冷却限制。
- 计划：`BATCH-2`

### WEB-003 · P2 · 已确认：多个上游响应在内存中无上限读取

- 状态：`OPEN`；组件：`upstream/http`；位置：`services/upstream_http_client.py:339-362`；`services/dynamic_query_service.py:335-354`；`services/image_asset_store.py:238-252`；`lanzou_update_push_api_server/providers.py`
- 证据与影响：文本路径直接访问 response.text，图片路径直接访问 response.content，均在完整缓冲后才解析或校验，未设置响应字节硬上限。 异常、恶意或被重定向的上游可返回超大响应，导致 Windows 服务内存耗尽或长时间阻塞。
- 修复与验收：统一使用流式下载、Content-Length 预检和按类型的硬字节上限；超限应记录结构化错误。 回归测试：为 JSON、HTML、图片和蓝奏 Provider 分别模拟超大分块响应。
- 计划：`BATCH-2`

### SEC-001 · P2 · 已确认：授权失败审计日志无轮转且读取时全量载入

- 状态：`OPEN`；组件：`lanzou-control/security`；位置：`lanzou_update_push_api_server/security.py:79-120`；`lanzou_update_push_api_server/maintenance.py:16-62`
- 证据与影响：每次未授权访问都会 append JSONL；文件没有大小、数量或时间保留策略，read_audit 会一次读取完整文件。 攻击者可通过大量拒绝请求填满磁盘，之后管理员查看审计又可能造成高内存。
- 修复与验收：使用轮转日志、保留上限和 tail 读取，并对重复拒绝事件做采样或限流。 回归测试：生成超过保留上限的拒绝事件，验证文件轮转且读取内存受限。
- 计划：`BATCH-2`

### DEP-001 · P1 · 依赖漏洞：锁定依赖版本命中 31 个唯一安全公告

- 状态：`OPEN`；组件：`dependencies`；位置：`requirements.txt`
- 证据与影响：pip-audit 在当前锁定集合中识别出 5 个包、31 个唯一 advisory：requests 2、urllib3 6、cryptography 3、Pillow 13、Starlette 7。版本层面已确认有已知漏洞，但每个漏洞在本项目中的可达性仍需单独判断。 可能包含请求走私、压缩/解析、图像处理或框架级拒绝服务风险；不能继续长期固定在已知脆弱版本。
- 修复与验收：先在独立分支升级并跑完整 Windows/生产契约测试，再按可达性给 advisory 分级；不要只升级单个传递依赖造成版本不兼容。 回归测试：升级后运行 pip-audit、227 项测试、图片渲染、FastAPI TestClient、真实 Windows 启动验收。
- 计划：`BATCH-1`

### SO1-001 · P2 · 高概率：响应回调闭包可能跨重试写入下一轮状态

- 状态：`OPEN`；组件：`so1/browser`；位置：`so1_client.py:194-277`
- 证据与影响：handle_response 闭包引用 responses 和 response_tasks，外层重试会重新绑定这两个变量；旧页面的延迟回调理论上可把任务和响应写入下一次尝试。Ruff B023 同样标记了该闭包绑定风险。 极端网络延迟或页面关闭竞态下，可能混合两次尝试的数据，产生错误战绩或悬挂任务。
- 修复与验收：用每次尝试的回调工厂/默认参数绑定局部对象；关闭 context 前注销 listener 并取消、排空所有任务。 回归测试：模拟第一次尝试延迟响应在第二次尝试开始后到达，断言状态完全隔离。
- 计划：`BATCH-2`

### SO1-002 · P2 · 已确认：So1Client 单例会忽略后续配置并复用旧事件循环对象

- 状态：`OPEN`；组件：`so1/lifecycle`；位置：`so1_client.py:20-44`
- 证据与影响：__new__ 返回进程级单例，__init__ 检测 _initialized 后直接返回。后续用新账号、密码、headless、timeout 或 SO1_MAX_CONCURRENT_PAGES 创建实例都不会生效，asyncio.Lock/Semaphore 也来自旧生命周期。 测试、热重载或同进程重建应用时可能继续使用旧凭据和旧并发配置，甚至触发跨事件循环错误。
- 修复与验收：移除全局单例，由 AppContext 管理唯一实例；或显式实现可验证的 reconfigure/close 生命周期。 回归测试：同进程创建两套不同配置，验证第二套生效且可以在新事件循环正常使用。
- 计划：`BATCH-2`

### HLTH-001 · P2 · 已确认：SO1 readiness 只检查浏览器连接，不检查登录会话

- 状态：`OPEN`；组件：`health/so1`；位置：`routers/health.py:18-37,122-150`
- 证据与影响：健康检查把 Chromium 进程连接视为 so1_browser=up；未验证账号配置、cookie、验证码状态或 /user/me。 浏览器正常但会话失效时 /readyz 仍可能判定可接管流量，真实战绩请求随后失败。
- 修复与验收：增加带 TTL 的认证会话探针，并区分 browser_up、session_authenticated、challenge_required。 回归测试：空凭据、过期 storage_state、验证码状态下 readiness 必须降级。
- 计划：`BATCH-2`

### HLTH-002 · P2 · 设计风险：全局 readiness 将互不相关功能硬绑定到 MySQL 和 SO1

- 状态：`OPEN`；组件：`health/readiness`；位置：`routers/health.py:81-150`；`core/context.py:45-48`
- 证据与影响：当前 ready 要求 MySQL 和浏览器同时可用，但骗子/同行、蓝奏、部分动态查询和本地快照具有不同依赖；Context 注释也明确 MySQL 故障不应禁用独立风险存储。 单一可选子系统故障会让负载均衡移除整个服务；相反，单一 ready=true 也不能证明每个业务功能健康。
- 修复与验收：提供 component/capability readiness，并让调用方按 feature 判断可用性；全局 ready 只表达真正的核心门禁。 回归测试：组合故障矩阵：MySQL down、SO1 down、风险库可用、快照可用时验证各 feature 状态。
- 计划：`BATCH-2`

### LZ-002 · P2 · 已确认：配置加载路径未拒绝空或重复 watcher ID

- 状态：`OPEN`；组件：`lanzou/config`；位置：`lanzou_update_push_api_server/config.py:53-61,116-137`；`lanzou_update_push_api_server/monitor.py:533-534`
- 证据与影响：WebUI 保存路径有部分校验，但直接配置文件/环境加载允许重复 ID；watcher_map 以字典覆盖较早项，而 scan_all 仍遍历原列表。最小复现 2 个同 ID watcher 最终 map 只剩后一个。 状态、锁、快照和手动扫描会指向不同 watcher，可能漏扫、串状态或覆盖历史。
- 修复与验收：在 AppConfig 构造/加载的唯一入口统一 trim、非空、格式和唯一性校验。 回归测试：文件加载和 WebUI 保存都拒绝空白、重复和大小写/空格规范化后冲突的 ID。
- 计划：`BATCH-2`

### LZ-003 · P3 · 已确认：scan_on_start=false 时服务可能长期保持 never_scanned 降级

- 状态：`OPEN`；组件：`lanzou/readiness`；位置：`lanzou_update_push_api_server/monitor.py:569-633,646-657`
- 证据与影响：后台循环首轮直接跳过扫描，随后等待完整 scan_interval_seconds；readiness 又把所有未扫描 watcher 计为 degraded。扫描间隔允许很长。 刚启动的服务可能数小时甚至一天返回 503，即使这是配置明确要求的不立即扫描。
- 修复与验收：将 warmup/not-yet-scheduled 与故障分开，或在不通知的情况下建立首轮基线。 回归测试：scan_on_start=false + 长间隔时 readiness 应表达 warming 而非 failed。
- 计划：`BATCH-3`

### LZ-004 · P3 · 已确认：WebUI 配置更新使用宽松布尔和方法解析

- 状态：`OPEN`；组件：`lanzou/config`；位置：`lanzou_update_push_api_server/management.py:248-340`；`lanzou_update_push_api_server/providers.py:378-382`
- 证据与影响：scan_on_start 使用 bool(value)，JSON 字符串 'false' 会被解释为 True；WER method 未限制为 GET/POST，Provider 将任何非 POST 值静默按 GET 处理；部分超时值未统一约束。 手工 API、旧客户端或错误表单会保存与用户输入不一致的配置，且错误被静默掩盖。
- 修复与验收：配置加载和更新共用严格 Schema/normalizer，非法值返回 400/422。 回归测试：覆盖字符串 false、非法 method、NaN/负数/超范围 timeout。
- 计划：`BATCH-3`

### LZ-005 · P2 · 高概率：热更新同 ID watcher 时未与正在执行的旧扫描串行化

- 状态：`OPEN`；组件：`lanzou/concurrency`；位置：`lanzou_update_push_api_server/monitor.py:549-567`
- 证据与影响：reload_config 只为被删除的 ID 获取锁；URL、密码、页数或 Provider 设置变化但 ID 不变时，旧扫描仍可在新配置生效后提交旧快照或旧事件。 配置保存后可能短暂使用旧地址，并把旧来源结果覆盖到新 watcher 状态。
- 修复与验收：识别所有发生语义变化的 watcher 并获取其锁，或在扫描提交前校验配置 generation。 回归测试：让旧扫描阻塞，热更新相同 ID 的 URL 后释放旧扫描，断言旧结果不会提交。
- 计划：`BATCH-2`

### LZ-006 · P3 · 设计风险：没有启用通知目标时变化会永久保持 pending

- 状态：`OPEN`；组件：`lanzou/delivery`；位置：`lanzou_update_push_api_server/monitor.py:852-913`
- 证据与影响：检测到变化且 notify=true 时，0 个启用目标产生 delivery_state=skipped；快照不提交并标记 notification_pending，后续扫描会反复看到同一差异。 关闭通知并不会暂停通知语义，而是造成永久降级、重复差异和潜在恢复后群发旧变化。
- 修复与验收：明确无通知目标策略：提交基线、暂停 watcher 或标记配置错误；不能无限 pending。 回归测试：0 个启用目标下连续扫描同一变化，断言状态和快照符合选定策略且不重复积压。
- 计划：`BATCH-3`

### PROV-001 · P2 · 高概率：WER 递归提取器可能把容器对象当成文件

- 状态：`OPEN`；组件：`lanzou/wer-provider`；位置：`lanzou_update_push_api_server/providers.py:403-450`
- 证据与影响：提取器只要字典含 name/title/url/id 就先加入结果，再递归 files/items/children。最小样例容器 name=container、子项 a.zip 会同时返回两个文件，其中 container 是伪文件。 部分 WER API 包装结构会制造伪新增/删除，导致蓝奏更新误报。
- 修复与验收：按已知响应 Schema 识别叶子节点；有 children/files 的容器默认不作为文件，最后按 canonical key 去重。 回归测试：覆盖分页容器、目录、文件叶子和重复嵌套。
- 计划：`BATCH-2`

### XQ-001 · P2 · 高概率：Riot ID 查询失败后按纯名称回退可能返回错误玩家

- 状态：`OPEN`；组件：`cross-query`；位置：`services/cross_query_service.py:60-69`
- 证据与影响：name#tag 基础查找失败时会去掉 #tag 重试，再合并回退结果；代码未验证返回账号的 gameName/tagLine 与原始 Riot ID 一致。 同名玩家存在时，用户可能收到另一个 tag 的战绩而不是明确的未找到。
- 修复与验收：仅在上游能确认唯一账号时回退，并校验返回 Riot ID；否则保留原始失败。 回归测试：模拟同 gameName 不同 tag，确保不会跨 tag 成功。
- 计划：`BATCH-2`

### ADMIN-001 · P2 · 已确认：诊断逻辑硬编码端口、Windows 路径和服务语义

- 状态：`OPEN`；组件：`admin/diagnostics`；位置：`lanzou_update_push_api_server/management.py:452-497`
- 证据与影响：诊断固定检查 5001、6178、3306 和 .venv/Scripts/python.exe，没有读取 APP_PORT、蓝奏端口、MYSQL_PORT；非 Windows 平台 service_ok 固定为 False，而总 ok 又依赖它。 自定义端口、不同虚拟环境或非 Windows 环境会被误报故障，可能误导运维执行错误修复。
- 修复与验收：从实际 AppConfig/env/build-info 获取目标；不适用检查标记 N/A，不计入失败。 回归测试：自定义三个端口、Linux、无 Windows 服务三组诊断结果。
- 计划：`BATCH-2`

### ADMIN-002 · P2 · 已确认：配置管理 token 后，内置 API 调试器无法调用受保护的蓝奏接口

- 状态：`OPEN`；组件：`admin/debugger`；位置：`lanzou_update_push_api_server/server.py:183-195`；`lanzou_update_push_api_server/api_debugger.py:24-58`；`lanzou_update_push_api_server/security.py:59-69`
- 证据与影响：调试器通过新的 HTTP 请求回环调用 6178，但没有注入 x-admin-token；一旦 WEBUI_ADMIN_TOKEN 已配置，即使来源是 loopback 也必须提供 token。 启用推荐安全配置后，管理页面中的大部分蓝奏接口调试会返回 401。
- 修复与验收：优先在服务内直接 dispatch；必须回环时由服务端注入 token，且不得把 token 返回浏览器。 回归测试：设置 WEBUI_ADMIN_TOKEN 后，通过 /admin/invoke 调用受保护的 GET/POST 均成功，浏览器响应不含 token。
- 计划：`BATCH-2`

### API-001 · P2 · 已确认：非法蓝奏配置更新返回 500 而不是客户端错误

- 状态：`OPEN`；组件：`lanzou-api`；位置：`lanzou_update_push_api_server/server.py:155-169`
- 证据与影响：admin_save_main_config 显式捕获 ValueError 并返回 400；admin_save_lanzou_config 直接调用 update_lanzou_config，校验 ValueError 会冒泡为 500。 WebUI 把输入错误显示为服务器内部故障，监控和调用方也无法区分是否应重试。
- 修复与验收：捕获 ValueError/配置校验异常并返回 400 或 422，保留结构化字段错误。 回归测试：非法 watcher、method、timeout 和路径均返回 4xx，不写配置文件。
- 计划：`BATCH-2`

### OPS-001 · P1 · 已确认：正式接管脚本可能强制结束其他项目的 app.py 进程

- 状态：`OPEN`；组件：`operations/takeover`；位置：`ops/formal_service_takeover.ps1:3-6,95-114`
- 证据与影响：脚本按 Python 命令行包含 app.py 匹配进程，没有校验脚本完整路径或工作目录，然后执行强制停止；项目根目录还固定为 D:\project2\lolapisevers。 同机其他 Python 服务只要入口名为 app.py 就可能被误杀，造成非本项目生产中断。
- 修复与验收：匹配完整规范化入口路径、项目根和预期父进程；根目录参数化，并先输出 dry-run 清单。 回归测试：同时运行本项目 app.py 和另一个目录 app.py，接管只能停止前者。
- 计划：`BATCH-1`

### OPS-002 · P1 · 已确认：持久化安装在验证新服务前先删除现有服务

- 状态：`OPEN`；组件：`operations/persistence`；位置：`ops/install_persistence.ps1:48-72`
- 证据与影响：脚本先 stop/remove 现有 NSSM 服务，再执行 install/config/start；后续任一步失败都没有恢复旧服务定义。 安装失败会让生产服务完全消失，且无法依赖脚本自动回滚。
- 修复与验收：保存现有服务配置并事务化切换；先验证候选命令、路径、权限和端口，再替换，失败时恢复旧定义。 回归测试：人为让新 install 或 start 失败，断言旧服务自动恢复并运行。
- 计划：`BATCH-1`

### OPS-003 · P2 · 已确认：NSSM 下载后未做完整性验证即以管理员权限执行

- 状态：`OPEN`；组件：`operations/supply-chain`；位置：`ops/install_persistence.ps1:16-32`
- 证据与影响：脚本从互联网下载 ZIP、解压并执行 nssm.exe，没有固定 SHA-256、签名或可信发布清单校验。 下载源、DNS、代理或镜像被篡改时可直接获得 Windows 管理员/SYSTEM 级代码执行。
- 修复与验收：随发布包附带已验证二进制，或固定版本和 SHA-256，并校验 Authenticode/发布者。 回归测试：篡改一个字节后安装必须在执行前失败。
- 计划：`BATCH-2`

### OPS-004 · P2 · 已确认：健康检查和接管失败日志仍读取过期文件名

- 状态：`OPEN`；组件：`operations/diagnostics`；位置：`ops/health_check.ps1:3-13`；`ops/formal_service_takeover.ps1:228-233`；`ops/run_service.ps1:79-85`
- 证据与影响：health_check 和 takeover 读取 service.stdout.log/service.stderr.log，而当前 supervisor 将主 API 输出写入 main_api.stdout.log/main_api.stderr.log；路径和端口也有硬编码。 真正启动错误可能被隐藏，运维看到旧日志后做出错误判断。
- 修复与验收：日志文件名、项目根和端口统一由一个共享配置/脚本模块生成。 回归测试：制造主 API 启动失败，两个运维脚本必须展示当前 main_api.stderr.log 的同一错误。
- 计划：`BATCH-2`

### CFG-001 · P3 · 已确认：核心整数环境变量缺少安全解析和范围校验

- 状态：`OPEN`；组件：`core/config`；位置：`core/config.py:35-59`
- 证据与影响：多个端口、超时、缓存和并发值直接 int(os.getenv(...))；非数字会在启动阶段抛异常，0 或负数也可能进入运行时。 一个拼写错误即可让服务无法启动，或产生无效端口、零缓存、异常并发和超时。
- 修复与验收：使用统一 bounded_int/bounded_float，汇总所有配置错误后给出可读启动失败报告。 回归测试：覆盖空值、非数字、负数、零和超范围。
- 计划：`BATCH-3`

### DB-001 · P3 · 已确认：数据库名和字符集被直接插入 CREATE DATABASE SQL

- 状态：`OPEN`；组件：`mysql/config`；位置：`db.py:45-58`
- 证据与影响：数据库名放入反引号、charset 直接拼接，未验证 MySQL 标识符或允许字符集。参数来自环境配置。 包含反引号或非法字符的配置会破坏初始化 SQL；在配置来源失守时扩大 SQL 注入面。
- 修复与验收：数据库名只允许安全标识符字符，charset 从固定白名单选择。 回归测试：拒绝反引号、空格、分号和未知 charset，合法 utf8mb4 正常创建。
- 计划：`BATCH-3`

### SEC-002 · P3 · 条件风险：未配置 token 时的 loopback 信任在本地反向代理后会失效

- 状态：`OPEN`；组件：`lanzou-control/security`；位置：`lanzou_update_push_api_server/security.py:59-69`
- 证据与影响：token 为空时只要 request.client 是 loopback 就授权。若未来由本机 Nginx/Caddy/端口转发代理公网或局域网请求，后端看到的客户端仍是 127.0.0.1。 在该部署条件下，远程用户可获得全部控制 API 权限。当前是否可利用取决于实际代理拓扑。
- 修复与验收：代理部署必须强制 WEBUI_ADMIN_TOKEN；实现明确 trusted proxy 和原始客户端地址策略，不能仅凭 socket 来源。 回归测试：通过 loopback 反向代理转发远程请求，未带 token 必须被拒绝。
- 计划：`BATCH-3`

## 依赖漏洞摘要

`DEP-001` 是版本级事实，并不表示所有公告都能从本项目路径直接利用；升级后仍需做可达性与兼容性验证。

| 包 | 当前版本 | 唯一公告数 | 修复全部本次公告的观察下限 |
|---|---:|---:|---|
| `requests` | `2.32.3` | 2 | `2.33.0` |
| `urllib3` | `2.2.2` | 6 | `2.7.0` |
| `cryptography` | `46.0.5` | 3 | `48.0.1` |
| `Pillow` | `12.2.0` | 13 | `12.3.0` |
| `starlette` | `0.38.6` | 7 | `通过兼容的 FastAPI/Starlette 升级确定` |

## 已排除的扫描误报

- `db.py` 的动态 WHERE 由固定片段组成，值仍使用参数绑定，未按 SQL 注入登记。
- 部分 requests timeout 通过变量或 kwargs 传入，扫描器无法识别；已逐处人工核对。
- SHA-1 仅用于非安全缓存/同步指纹，不用于认证或签名。
- 宽泛异常捕获多数属于降级、截图和审计容错；只有影响正确性的路径被登记。
- PowerShell `ExecutionPolicy Bypass` 本身是当前启动方式；供应链、误杀和回滚问题已单独登记。

## 修复顺序

### BATCH-1：阻断串号、数据污染、协议丢失、公开写入、SSRF 和部署中断

`GG-001`、`LZ-001`、`GG-002`、`GG-006`、`GG-007`、`DYN-001`、`WEB-001`、`DEP-001`、`OPS-001`、`OPS-002`

### BATCH-2：修复客户端兼容、认证边界、竞态、诊断和运维安全

`GG-003`、`GG-004`、`GG-005`、`GG-008`、`CR-001`、`WEB-002`、`WEB-003`、`SEC-001`、`SO1-001`、`SO1-002`、`HLTH-001`、`HLTH-002`、`LZ-002`、`LZ-005`、`PROV-001`、`XQ-001`、`ADMIN-001`、`ADMIN-002`、`API-001`、`OPS-003`、`OPS-004`

### BATCH-3：统一配置语义、readiness 和条件性部署风险

`LZ-003`、`LZ-004`、`LZ-006`、`CFG-001`、`DB-001`、`SEC-002`

每批必须执行：新增失败测试 → 最小修复 → Windows/Linux 全量测试 → WebUI JS 检查 → 隔离实机验收 → 再部署。

## 尚需实机验证

1. 真实 MySQL 初始化、断线、慢查询和配置边界。
2. 真实 SO1 登录态、过期 cookie、验证码、同名不同 tag 和跨重试延迟响应。
3. 真实蓝奏/WER 样本、Provider 切换、空列表保护和热更新竞态。
4. SnowLuma/NapCat 对 text/image/forward、Base64 和失败回退的消费边界。
5. 隔离 Windows 虚拟机中的 NSSM 安装失败回滚、服务接管误杀保护和任务计划恢复。
6. 多并发、重启、磁盘写满和超大响应故障注入。

## 关闭条件

问题只有在“旧代码可稳定复现、修复测试先行、全量测试通过、相关文档同步、P1/竞态/PowerShell 项完成实机验收、提交与部署可追溯”全部满足后，才可从 `OPEN` 改为 `FIXED`。
