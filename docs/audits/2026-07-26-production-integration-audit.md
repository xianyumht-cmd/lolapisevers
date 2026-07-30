# 生产业务对接审查（2026-07-26）

审查结论：**部分通过（partial pass）**。

核心战绩、合集、海符榜 JSON 和蓝奏回调链路可以工作；但后台查询测试器、健康状态、封号本地接口、回调重试语义、海符榜图片耗时和生产通知文案存在已复现缺陷。当前业务可以继续运行，但不能把管理页面的“成功”或三个健康端点的单一布尔值当作生产验收依据。

本报告对应的机器事实源是 [2026-07-26-production-integration-audit.json](./2026-07-26-production-integration-audit.json)。

## 审查范围

- 服务端：`xianyumht-cmd/lolapisevers`，基线 `e092a2134d281c4bd4987cc18f98aaf4af8e7ce9`
- 插件端：`xianyumht-cmd/my-napcat-sys`，基线 `e44dfce91d49babaa9ddcaa1acde12b895b66f0e`
- 授权测试群：`805402626`
- 排除项：公网暴露、接口鉴权和互联网攻击面
- 凭据处理：报告未写入生产密码、管理 token、OneBot token 或完整消息 ID

生产实际是两机拓扑：

| 节点 | 组件 | 端口/路径 |
|---|---|---|
| `192.168.3.89` | SnowLuma + GroupGuard | GroupGuard `6108`；部署目录 `/mnt/sda1/groupguard/app` |
| `192.168.3.100` | LOL 主 API | `5001` |
| `192.168.3.100` | 蓝奏监控 API | `6178` |

生产 GroupGuard 已正确覆盖为 `.100:5001` 和 `.100:6178`；源码中的 `.94:5000` 只是过期默认值。

## 生产实测结果

| 测试 | 结果 | 关键证据 |
|---|---|---|
| 服务端本地测试 | 通过 | 51/51 |
| 插件端本地测试 | 通过 | `npm test` 全部通过 |
| `5001 /health` | 有限制地通过 | HTTP 200、`ready=true`，但不覆盖封号/蓝奏等业务依赖 |
| 指定战绩直连 | 通过 | `ZCG烧火棍丘丘人#73557`，HTTP 200、live、约 6.21 秒 |
| 指定战绩管理测试 | 失败且误报成功 | 插件使用 `qq=`，上游 422，外层仍 `ok:true` |
| 合集 JSON / 图片 | 通过 | HTTP 200；图片约 0.45 秒 |
| 海符榜 JSON | 通过 | HTTP 200 |
| 海符榜图片 | 降级 | 服务约 21.25 秒，超过插件 20 秒超时；20 秒客户端得到 0 字节超时 |
| 指定封号的 lolapisevers 接口 | 失败 | `2621735529`，HTTP 503 |
| 指定封号的插件管理测试 | 通过 | 实际走另一个外部接口，上游 HTTP 200 |
| `6178 /health` | 部分通过 | 外层 `ok=true`；53 个当前 watcher 中 49 成功、4 失败，另有 10 个 orphan state |
| 蓝奏测试推送 | 通过但文案异常 | `.100:6178 → .89:6108 → 测试群` 成功，群消息状态 `sent` |
| 真人群命令 | 未验证 | 生产只有一个在线账号且 `reportSelfMessage=false`，机器人自发命令不会进入 GroupGuard |

真实群命令未被伪造发送。后续由测试群真人账号发送：

```text
查封号2621735529
查战绩 ZCG烧火棍丘丘人#73557
```

## 需要优先处理的问题

### P1：后台战绩测试协议错误并掩盖失败

`src/standalone/admin/query_api.ts:268-274` 构造 `/cross_query?qq=...`，而服务端 `routers/cross_query.py:16-27` 要求 `name`。同一测试器又在上游 422 时返回外层 `ok:true`，管理页面继续显示“接口已返回结果”。

正式群命令的 URL 构造是正确的（`src/services/interaction_service.ts:397-403,1755-1795`）。应让管理测试器直接复用正式适配器，并把上游非 2xx 传成外层失败。

### P1：蓝奏回调 ACK、重试和幂等协议不完整

GroupGuard 只要任一目标成功就返回成功；监控端只看 HTTP 2xx，不读取业务投递结果。重试又会生成新 UUID，并可能把已经成功的目标再次发送。

需要稳定 `event_id`、按目标持久化投递状态、明确 `complete/partial/duplicate/failed`，且只重试失败目标。

### P1：健康状态既会假绿也会假红

- `5001` 在本地封号接口 503 时仍 `ready=true`，MySQL 状态也不是实时 `SELECT 1`。
- `6178` 在 4 个当前 watcher 失败时仍 `ok=true`。
- `6108` 因一次启动身份探针失败显示 `healthy=false`、`botId` 为空，但最近消息投递是 5/5 成功。

应拆分 liveness、readiness、dependency、transport、identity 和 delivery 状态。

### P1：生产蓝奏通知模板已经损坏

实际模板为：

```text
检测到网盘更新?{title}???????
```

传输成功不等于内容正确。应立即修正生产配置，并增加中文/emoji 从配置保存到 QQ 落群的完整 round-trip 测试。

### P1：封号链路的真实来源不统一

生产插件通过外部封号接口成功，而 `lolapisevers /api/v2/lolban` 对同一指定样例返回 503。需要明确哪个服务是权威来源；若本地服务是正式契约，就必须恢复上游、加入 last-known-good 降级并纳入 readiness。

### P1：蓝奏变化识别存在误报群发风险

空抓取结果、provider 切换以及遗留 state 都可能产生全量 added/removed。当前已有 4 个失败 watcher 和 10 条孤儿状态作为风险前兆。应保护“非空 → 空”变化、统一跨 provider 文件身份，并在 URL/provider 变化时重新建立基线。

## P2 问题

- 海符榜图片稳定约 21.2 秒，超过插件 20 秒超时，只能在长等待后回退 JSON/文本。
- `查隐藏` 的后台宣称使用 local-api，但实际群命令走自定义 form 或直接 lolso1 bearer；海符榜完全不在查询概览中。
- 插件默认地址仍是 `.94:5000`，新装或配置恢复可能连接错误主机。
- 战绩快照读写与 live 查询耦合：数据库写失败可能遮蔽已经成功的 SO1 结果；旧快照又没有最大陈旧时间，插件也未展示 stale 元数据。
- 生产构建物没有 commit SHA：GroupGuard 只能记录 dist 哈希；5001 OpenAPI 仅为 `0.1.0`，6178 为 `0.3.1`。

## 已验证的正向结果

- 两仓本地测试基线均通过。
- 生产配置指向正确的 `.100:5001` 和 `.100:6178`。
- 指定战绩样例在正式 `cross_query` 契约下返回 live 数据。
- 合集 JSON/图片与海符榜 JSON 正常。
- 蓝奏测试事件成功经过监控、GroupGuard 并实际发送到授权测试群。

## 修复顺序

1. 修复后台战绩测试参数和 false-positive。
2. 修正生产通知模板。
3. 恢复或移除本地封号契约。
4. 让健康端点表达真实业务 readiness。
5. 实现回调稳定 ID、按目标 ACK 和幂等重试。
6. 优化海符榜图片耗时并补齐后台真实链路测试。
7. 统一默认配置、监控状态基线和构建 revision。

## 后续验收

- 管理测试器必须发送 `name/output/region`，上游 422 时外层不得成功。
- 相同蓝奏事件重复 POST 两次，测试群只收到一次；两目标一失败时只重试失败目标。
- 冷/热海符榜图片 p95 必须低于调用方超时并留出余量。
- 真人账号在测试群执行两条指定命令，记录等待提示、最终回复、次数、耗时、数据源和降级状态。
- 每个生产 health 响应可读出实际 Git commit，并能映射到对应远端。

## Git 安全

本次报告提交只能包含：

```text
docs/audits/2026-07-26-production-integration-audit.json
docs/audits/2026-07-26-production-integration-audit.md
```

服务仓已有 4 个运行时备份/坏状态文件未跟踪，可能包含本地配置或历史状态，禁止暂存：

```text
lanzou_update_push_api_server/config.json.bak.20260722T073942019643Z
lanzou_update_push_api_server/config.json.bak.20260722T074755644574Z
lanzou_update_push_api_server/providers.py.bak-20260722-212940
lanzou_update_push_api_server/state.json.bad.20260720-164752
```
