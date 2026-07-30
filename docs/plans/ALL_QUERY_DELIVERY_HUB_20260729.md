# lolapisevers 全查询统一交付中心执行计划（2026-07-29）

> 计划 ID：`GGK-ALL-QUERY-HUB-20260729`  
> 接口仓库：`xianyumht-cmd/lolapisevers`  
> 消费仓库：`xianyumht-cmd/groupguard-system`  
> 当前状态：`executing`  
> 架构目标：Windows 内网接口拥有全部内置业务查询、上游访问、业务处理和最终交付；SnowLuma 与未来官方机器人只做入口、权限、限流、协议调用和平台发送。

## 1. 审查结论

原计划 `GGK-INTRANET-QUERY-20260728` 的边界原则正确，且已完成统一快照、上游客户端、合集、ARAM、封号、交付协议、可观测性和跨仓契约。生产已部署目标提交 `8de85a855b8338c3a9a69cbb2a937cd0a6ef8b82`，`查合集 滑板鞋` 已经由 SnowLuma 通过内网接口完成真人验收。

但原计划的实际交付范围仍不足：

- `/api/v1/groupguard/query` 目前只支持 `shard`、`aram`、`lolban`；
- `查战绩` 仍由插件读取 `/cross_query` 原始/pretty 数据并决定图片与文字降级；
- `查隐藏` 仍由插件保存 Token/Key、访问公网 Provider、解析和格式化；
- `查骗子` 仍由插件访问第三方接口、合并本地库并格式化；
- `查同行` 的业务数据库仍只存在于插件端；
- `举报骗子/举报同行` 若不迁移，未来官方机器人无法共享同一风险数据源；
- 动态 HTTP 查询 Provider 仍可能绕过内网服务。

因此，原计划升级为“全查询统一交付中心”。生产已完成的合集迁移不回滚，后续在新分支增量实施。

## 2. 强制边界

所有内置业务查询必须遵循：

```text
SnowLuma / 官方机器人
  -> 发送标准化原始参数到 Windows 内网接口
  -> 接口访问公网或业务数据库
  -> 接口完成解析、归一化、排序、绘图、缓存、重试和降级
  -> 接口返回 groupguard-query-delivery.v1（后续兼容升级）
  -> 客户端只执行平台发送
```

客户端不得：

- 保存第三方 Provider 的 Token、Cookie、Key 或公网 URL；
- 解析上游业务 JSON/HTML；
- 决定图片、文字或合并转发降级；
- 合并多个 Provider 结果；
- 在接口失败时直连公网兜底；
- 保存作为跨客户端共享事实源的风险业务数据库。

## 3. 全查询清单

### 3.1 已完成生产迁移

| feature | 群命令 | 状态 |
|---|---|---|
| `shard` | `查合集` | 接口与插件均已部署，真人验收通过 |

### 3.2 接口已支持、插件待迁移

| feature | 群命令 | 当前偏离 |
|---|---|---|
| `aram` | `海符榜` | 插件仍自行请求图片/JSON并决定降级 |
| `lolban` | `查封号` | 插件仍维护 Provider 循环、解析状态和生成文案 |

### 3.3 接口能力待补齐

| feature | 群命令 | 需要的服务能力 |
|---|---|---|
| `battle` | `查战绩` | 复用 `query_cross` 与图片渲染，返回最终交付载荷 |
| `hidden` | `查隐藏` | Provider 凭据、两段查询、归一化、文案和降级全部移入接口 |
| `scammer` | `查骗子` | 第三方查询、本地风险库、合并、缓存与最终文本移入接口 |
| `peer` | `查同行` | 同行风险数据库与最终文本移入接口 |
| `scammer_report` | `举报骗子` | 写入共享风险库，并可选同步第三方举报端点 |
| `peer_report` | `举报同行` | 写入共享风险库 |

### 3.4 后续统一范围

- WebUI 管理测试器必须复用正式查询服务；
- SnowLuma 中旧的 LOL Token/Key、封号 Provider、视频 Provider、骗子 Provider 配置迁移到接口端；
- 动态 HTTP 查询命令必须改为调用内网查询代理，或通过独立 ADR 获批；
- 未来官方机器人直接消费相同协议，不复制任何查询业务实现。

不属于本计划的内容：纯群管控制、权限管理、签到积分、邀请统计、群成员实时信息等与 QQ 会话本身绑定的管理功能。

## 4. 执行步骤

### AQ-DOC-001：全查询范围和双仓计划

状态：`completed`

交付：

- 本文档与同名 JSON；
- GroupGuard 同步计划；
- 两仓架构规则补充。

### AQ-FAST-001：迁移 ARAM 与封号插件链路

状态：`in_progress`

依赖：生产接口已经支持 `aram` 和 `lolban`。

改动：

- GroupGuard 新增统一内网命令插件接管 `海符榜`、`查封号`；
- 一次命令只调用一次 `/api/v1/groupguard/query`；
- 删除旧互动路由对这两个命令的声明；
- 禁止插件端 Provider 循环、JSON 解析、图片探测和业务文案；
- 保留权限、群开关、限流、@ 提取和 OneBot 发送。

完成标准：

- CI、SnowLuma 构建、契约测试通过；
- ARM 替换 `dist` 后，`海符榜 亚索` 和 `查封号 QQ号` 真人通过；
- 接口断开时只显示固定传输失败提示，不访问公网。

### AQ-BATTLE-001：战绩最终交付

状态：`planned`

改动：

- 在服务端为 `battle` 增加统一交付；
- 复用 `query_cross`、`build_cross_image_response` 和现有格式化数据；
- 服务决定图片/转发/文本选择与降级；
- 插件只上传玩家 ID、大区、能力和偏好。

### AQ-HIDDEN-001：隐藏战绩服务化

状态：`planned`

改动：

- Provider URL、Key、Token 迁入接口本机受限配置；
- 两段请求、字段归一化、状态文案、缓存和降级全部由接口完成；
- 插件删除 `lolQueryUrl/lolAuthKey/lolToken` 的业务使用和公网请求。

### AQ-VIDEO-001：视频查询服务化

状态：`planned`

改动：

- 视频 Provider 模板迁入接口；
- 接口完成请求、直链提取、URL/媒体类型校验、缓存和最终文本；
- 插件只传分类并发送返回内容。

### AQ-RISK-001：风险查询共享服务

状态：`planned`

改动：

- 建立接口端风险库和迁移工具；
- 迁移骗子/同行记录、查询缓存、第三方查询和合并规则；
- 提供 `scammer`、`peer` 最终交付；
- GroupGuard 本地库仅保留迁移期只读备份，验收后停止作为事实源。

### AQ-RISK-WRITE-001：风险举报共享写入

状态：`planned`

改动：

- 提供经过鉴权和限流的举报 API；
- 支持幂等键、证据长度限制、去重和审计；
- 官方机器人与 SnowLuma 写入同一数据库。

### AQ-DYNAMIC-001：动态 HTTP 查询收口

状态：`planned`

改动：

- 标记哪些动态命令属于外部查询；
- 改为接口端 Provider 注册和最终交付；
- 未经 ADR 的插件端公网 HTTP 查询在发布门禁中失败。

### AQ-OFFICIAL-BOT-001：官方机器人适配层

状态：`planned`

要求：

- 官方机器人只实现平台鉴权、限流、调用协议和平台发送；
- 与 SnowLuma 使用同一 feature、parameters、capabilities 和 delivery；
- 不允许复制业务字段解析、文案或绘图。

### AQ-GATE-001：全查询发布门禁

状态：`planned`

门禁：

- GroupGuard 内置业务查询运行路径没有公网业务域名；
- 插件配置不再保存 Provider 凭据；
- 所有正式命令与 WebUI 测试器使用同一内网客户端；
- 每个 feature 有成功、参数错误、上游失败、快照/陈旧、协议错误和客户端发送计划测试；
- 两仓固定提交契约通过；
- 先接口端部署，再插件端部署。

## 5. 执行顺序

```text
AQ-DOC-001
  -> AQ-FAST-001 (aram + lolban)
  -> AQ-BATTLE-001
  -> AQ-HIDDEN-001
  -> AQ-VIDEO-001
  -> AQ-RISK-001
  -> AQ-RISK-WRITE-001
  -> AQ-DYNAMIC-001
  -> AQ-OFFICIAL-BOT-001
  -> AQ-GATE-001
```

## 6. 当前操作规则

- 当前生产 `查合集` 已通过，不回滚。
- PR #17 和 GroupGuard 现有堆叠 PR 在新阶段验收前仍不直接合并。
- 每个批次独立 CI、独立部署和真人验收。
- 插件旧实现可短期保留为不可达迁移代码，但不得重新注册为公网兜底。
- Provider 秘密只能存放在 Windows 接口本机受限配置。
