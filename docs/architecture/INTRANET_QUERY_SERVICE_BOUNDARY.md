# lolapisevers 内网查询服务边界（强制规则）

> 状态：规范性文档（normative）  
> 生效范围：LOL 查询、第三方数据抓取、业务处理、最终交付载荷、缓存与降级  
> 消费方：`xianyumht-cmd/groupguard-system`

## 1. 核心原则

`lolapisevers` 是内网业务服务，也是 LOL 查询链路唯一允许访问公网业务数据源的组件。

SnowLuma / GroupGuard 只负责命令入口、权限与限流、调用本服务，以及执行 OneBot 发送。以下工作必须集中在本服务：

- 公网上游访问；
- 英雄别名和业务字段归一化；
- HTML/JSON 解析；
- 数据校验、过滤、排序、评分和聚合；
- 最终图片和最终文本生成；
- 重试、限速、熔断、并发合并；
- 内存缓存、持久化快照和 last-known-good；
- stale/snapshot 降级判定；
- 上游凭据与 Provider 配置；
- 可观测性、依赖状态和发布追溯。

标准链路：

```text
GroupGuard 内网请求
  -> lolapisevers 读取热缓存
  -> 必要时读取磁盘快照
  -> 在受控条件下访问公网上游并刷新快照
  -> 完成业务解析、绘图和降级选择
  -> 返回最终交付载荷
  -> GroupGuard 仅执行 OneBot 发送
```

## 2. 最终交付载荷

长期协议名：

```text
groupguard-query-delivery.v1
```

服务应返回已经可以直接发送的载荷，而不是要求插件解释业务数据。最小结构：

```json
{
  "contract": "groupguard-query-delivery.v1",
  "request_id": "stable-request-id",
  "ok": true,
  "command": "lol_shard",
  "delivery": {
    "kind": "image_url",
    "text": "",
    "url": "http://192.168.3.100:5001/...",
    "nodes": []
  },
  "meta": {
    "source": "live|cache|stale|snapshot",
    "updated_at": "2026-07-28T00:00:00+08:00",
    "stale": false,
    "stale_age_seconds": 0,
    "cache_expires_in": 600,
    "upstream": "redacted-provider-name",
    "warnings": []
  },
  "error": null
}
```

初始允许的 `delivery.kind`：

- `text`
- `image_url`
- `forward`
- `none`

服务必须自行决定图片失败后的文本降级，且用户可见文本必须已经格式化完成。插件不得重新解析 `rows`、胜率、选率、状态或上游错误。

## 3. 兼容策略

现有接口继续保留：

- `/cross_query`
- `/shard_query`
- `/aram_augments`
- `/api/v2/lolban`

迁移阶段可以为现有接口增加 `output=delivery`，或增加统一 `/api/v3/query`。无论采用哪种路径，都必须：

1. 保持旧调用方可用；
2. 使用相同服务函数，不复制业务实现；
3. 返回完整契约版本；
4. 对未知命令和未知输出类型返回明确 4xx；
5. 不在响应中暴露 Provider 凭据、Cookie、Token 或完整敏感 URL。

## 4. 持久化快照规则

重要上游数据不得只存内存。建议统一存放在：

```text
data/upstream_snapshots/
```

每份快照至少包含：

- `schema_version`
- `source_id`
- `captured_at`
- `content_sha256`
- `payload`
- `source_etag`（若有）
- `source_last_modified`（若有）
- `last_refresh_error_class`
- `last_refresh_error_at`

写入要求：

1. 先写临时文件；
2. `flush/fsync`；
3. 原子替换；
4. 读取时校验 JSON、schema 和哈希；
5. 损坏文件保留时间戳备份，不得静默覆盖；
6. 运行时文件必须被 Git 忽略；
7. 快照必须有最大允许陈旧时间，不得无限伪装为实时数据。

## 5. 上游访问规则

统一上游客户端至少支持：

- 分离连接超时和读取超时；
- 有上限的重试，默认只对网络错误、429 和部分 5xx 重试；
- 指数退避与抖动；
- 每个 source 的 singleflight；
- 连续失败后的短期熔断；
- 条件请求（ETag / Last-Modified）能力；
- 结构化错误类别：DNS、connect、read timeout、TLS、HTTP、parse、schema；
- 日志记录 source_id，不记录敏感完整 URL；
- 失败时优先使用符合最大年龄的快照。

禁止在每条群命令中无条件并发刷新多个公网数据源。

## 6. 缓存与降级语义

必须区分：

- `live`：本次成功访问上游；
- `cache`：有效内存缓存；
- `snapshot`：服务启动后从磁盘恢复的有效快照；
- `stale`：上游刷新失败，但使用仍在最大陈旧窗口内的最后成功结果；
- `unavailable`：没有可接受的数据。

缓存到期不等于立即删除业务数据。推荐模式：

```text
fresh TTL 到期
  -> 仍保留 stale 值
  -> 单个刷新任务访问上游
  -> 成功则替换
  -> 失败则在最大陈旧窗口内继续服务并标明 stale
```

## 7. 健康与就绪语义

- `/livez`：只表示进程存活。
- `/readyz`：表示服务能处理约定的内网请求；不得只看进程和端口。
- 上游实时不可达不一定使整体服务不就绪：如果关键功能有可接受快照，应显示 `degraded` 而非完全不可用。
- 每个查询依赖应单独暴露：`live/cache/stale/unavailable`、最后成功时间、最后错误类别、快照年龄。
- 合集/英雄基础数据在没有任何快照时属于关键不可用；有受控快照时可以降级服务。
- build commit 必须继续包含完整 40 位提交。

## 8. 当前已确认的问题

### P1：通用 JSON 请求没有重试和降级

`utils/http_client.py` 当前只执行一次 `requests.get(..., timeout=10)`，没有重试、条件请求、错误分类或持久化降级。

### P1：合集与英雄表只有内存缓存

`services/shard_service.py` 在缓存缺失时依次访问两个公网源；任一超时就使请求失败。服务重启后没有快照可用。

### P1：ARAM 的英雄表与业务结果缺少持久化 LKG

生产分支已经具备并发合并和图片缓存优化，但英雄表仍依赖公网，OP.GG 业务结果也只在内存中。服务重启或缓存到期后仍可能直接 503。

### P1：封号 LKG 仅在内存中

`LolBanService` 已有受控 stale 语义，但 `_last_known` 是内存结构，重启后丢失。

### P2：已有持久化能力没有统一复用

图片素材已经使用持久化缓存，说明项目具备安全落盘基础；但查询业务数据没有统一快照组件。

## 9. 发布门禁

涉及查询服务的 PR 必须满足：

1. 新增公网源必须通过统一上游客户端。
2. 关键上游必须有持久化快照或明确说明为什么不允许降级。
3. 单元测试覆盖首次成功、热缓存、磁盘恢复、上游超时、损坏快照、过期快照和并发刷新。
4. 用户响应明确标注 `live/cache/snapshot/stale`。
5. `readyz` 和管理页面不得把 stale 伪装为 live。
6. 交付协议 fixture 与 GroupGuard 契约测试一致。
7. 服务端必须先部署，并证明兼容旧插件后，才能部署 GroupGuard。
8. 运行时快照、日志、配置和秘密不得提交到 Git。

## 10. 安全边界

- Provider URL、Token、Cookie 只放在本机受限配置中。
- 响应和日志只公开 Provider 名称和错误类别。
- 内网管理接口继续遵守现有管理令牌与回环限制。
- 快照文件权限应继承当前服务数据目录的安全 ACL。
