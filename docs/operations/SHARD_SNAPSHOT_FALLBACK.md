# 合集数据持久化与断网降级

## 目标

`/shard_query` 的公网数据访问全部由 `lolapisevers` 完成。GroupGuard 只调用内网接口，不再需要访问 GitHub Raw 或腾讯英雄列表。

本服务分别保存两个独立快照：

- `lol-shard-data.json`：合集统计数据；
- `lol-hero-list.json`：英雄名称、称号、关键词和 alias。

默认目录：

```text
data/upstream_snapshots/
```

可以通过 `UPSTREAM_SNAPSHOT_DIR` 修改。

## 查询顺序

内存缓存失效后，服务按以下顺序处理每个公网数据源：

1. 读取并校验本地快照；
2. 使用快照中的 `ETag` 和 `Last-Modified` 发起条件请求；
3. HTTP 200：校验数据结构，原子更新快照；
4. HTTP 304：继续使用本地正文，并刷新快照确认时间；
5. DNS、TLS、连接、读取超时或可重试 HTTP 错误：使用未超过最大年龄的快照；
6. 快照缺失、损坏或超过最大年龄：返回 HTTP 503，不伪装成实时结果。

损坏快照会自动隔离为带时间戳的 `.bad` 文件，随后尝试实时恢复。

## 返回状态

原有请求形式保持不变：

```http
GET /shard_query?hero=滑板鞋&output=json
GET /shard_query?hero=滑板鞋&output=image
```

JSON 结果新增以下兼容字段：

- `source=live`：公网数据实时成功，或条件请求返回 304；
- `source=cache`：本次命中进程内缓存，`cache_origin` 保留原始来源；
- `source=stale`：公网刷新失败，使用最近一次有效快照；
- `source=snapshot`：上游熔断期间直接使用快照；
- `stale`：是否正在使用未实时确认的数据；
- `snapshot_age_seconds`：使用快照时的最大年龄；
- `fallback_reason`：只包含安全的数据源 ID 和错误类别；
- `source_details`：两个数据源各自的模式、请求次数、HTTP 状态和快照状态。

返回内容不会暴露公网完整 URL、本地快照路径、账号、密码或查询 token。

## 配置

```powershell
$env:UPSTREAM_SNAPSHOT_DIR = "data\upstream_snapshots"
$env:SHARD_SNAPSHOT_MAX_AGE_SECONDS = "604800"
```

默认最大年龄为 604800 秒，即 7 天。最小允许值为 60 秒，最大允许值为 365 天。

## 发布验收

部署前必须通过：

1. 公网正常时查询返回 `source=live`，并生成两个快照；
2. 重启服务后切断公网，已查询英雄仍可返回 `source=stale`；
3. 快照超过最大年龄后，断网查询返回 HTTP 503；
4. 将一个快照改成损坏 JSON 后，文件被隔离，公网正常时自动恢复；
5. `/shard_query` 的 `hero`、`output=image|json` 和既有业务字段保持兼容；
6. GroupGuard 旧版本仍可继续使用当前接口，插件迁移不得先于服务端发布。
