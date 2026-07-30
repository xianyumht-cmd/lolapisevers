# ARAM 海符榜持久化与断网降级

## 目标

`/aram_augments` 的英雄目录和 OP.GG 页面访问全部由 `lolapisevers` 处理。GroupGuard 只调用内网接口，不访问腾讯英雄列表或 OP.GG。

服务保存两类持久化数据：

- `lol-hero-list.json`：与查合集共用的英雄目录快照；
- `aram-mayhem-{alias}.json`：每个英雄最后一次成功生成的标准化 ARAM 成品数据。

默认目录：

```text
data/upstream_snapshots/
```

## 英雄目录

英雄目录与查合集共用同一个数据源 ID 和快照文件，避免同一数据重复下载和维护。

刷新顺序：

1. 读取并校验本地快照；
2. 使用 `ETag` 和 `Last-Modified` 发起条件请求；
3. HTTP 200 时原子更新快照；
4. HTTP 304 时保留原正文和条件验证信息；
5. 公网失败时使用未超过 `SHARD_SNAPSHOT_MAX_AGE_SECONDS` 的快照；
6. 快照缺失、损坏或过期时返回 HTTP 503。

## 每英雄 ARAM 成品

强化符文页是必选数据，出装页是可选数据。两类页面仍保持并发抓取，避免增加正常查询耗时。

- 强化符文页成功：生成实时结果并保存每英雄成品快照；
- 强化符文页失败：使用未超过最大年龄的每英雄快照；
- 上游熔断：直接使用每英雄快照，减少重复等待；
- 出装页失败但强化页成功：优先复用旧成品快照中的出装、鞋子、召唤师技能和技能顺序；
- 快照写盘失败：不遮蔽已经成功生成的实时结果；
- 快照缺失、损坏或过期：返回 HTTP 503，不伪装成实时数据。

## 返回状态

原请求形式保持不变：

```http
GET /aram_augments?hero=阿狸&output=json
GET /aram_augments?hero=阿狸&output=image
```

原有业务字段、图片缓存键、图片 ETag 和 canonical singleflight 保持兼容。

新增或明确的状态字段：

- `source=opgg`：实时 OP.GG 结果；
- `source=cache`：进程内缓存，`cache_origin` 表示原来源；
- `source=stale`：实时强化页失败，使用最近有效成品快照；
- `source=snapshot`：上游熔断期间直接使用成品快照；
- `provider=opgg`：业务数据提供方；
- `stale`：最终业务数据是否为旧快照；
- `snapshot_age_seconds`：最终成品快照年龄；
- `fallback_reason`：安全的错误类别，不包含完整敏感 URL；
- `lookup_source`：英雄目录来自 live、stale、snapshot 或 cache；
- `timing.build_status=snapshot`：实时出装页失败，已复用旧成品中的可选数据。

## 配置

```powershell
$env:UPSTREAM_SNAPSHOT_DIR = "data\upstream_snapshots"
$env:SHARD_SNAPSHOT_MAX_AGE_SECONDS = "604800"
$env:ARAM_SNAPSHOT_MAX_AGE_SECONDS = "86400"
```

- 英雄目录默认最多使用 7 天内快照；
- 每英雄 ARAM 成品默认最多使用 24 小时内快照；
- `ARAM_SNAPSHOT_MAX_AGE_SECONDS` 最小 60 秒，最大 30 天。

## 发布验收

部署前必须通过：

1. 公网正常时查询返回 `source=opgg`，并生成英雄目录和对应英雄成品快照；
2. 重启服务并阻断 OP.GG 后，已成功查询过的英雄返回 `source=stale`；
3. 连续失败进入熔断后返回 `source=snapshot`；
4. 快照超过最大年龄后，断网查询返回 HTTP 503；
5. 出装页失败但强化页成功时，强化数据实时更新，可选出装数据从旧快照恢复；
6. 中文名、称号、英文 alias 查询仍映射到同一 canonical 缓存键；
7. 并发同英雄查询仍只生成一次业务成品；
8. 图片 ETag、图片缓存和既有 `/aram_augments` 请求参数保持兼容；
9. 服务端必须先部署和验收，之后才能迁移 GroupGuard。
