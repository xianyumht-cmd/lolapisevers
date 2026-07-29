# 查询链路安全观测接口

## 目的

`LAPI-OBS-001` 为查合集、英雄目录、海符榜和查封号提供统一、只读、脱敏的运行状态。

接口只读取：

- 进程内缓存数量；
- 上游客户端的熔断和并发状态；
- 持久化快照的有效性、年龄和最近刷新结果；
- 查封号服务已有的汇总健康状态。

接口不会主动请求 GitHub、腾讯、OP.GG、查封号上游或任何其他公网服务，因此查看状态不会制造额外公网流量，也不会触发新的查询。

## 地址

```http
GET /api/v1/operations/query-observability
```

正常、降级和部分不可用时均返回 HTTP 200，并通过顶层 `status` 表示整体状态：

- `ok`：四类查询源当前均为 `live` 或 `cache`；
- `degraded`：至少一类依赖 `snapshot`、`stale`，或已有部分功能 `unavailable`；
- `down`：四类查询源全部不可用。

只有应用上下文未创建时返回 HTTP 503，并返回安全的 `context_unavailable`。

## 数据模式

每个功能使用以下模式之一：

- `live`：当前进程中观察到最近一次实时成功；
- `cache`：当前有可直接使用的进程内缓存；
- `snapshot`：没有实时确认，当前主要依赖有效持久化快照；
- `stale`：最近刷新失败，但仍有未过期快照或最近成功结果可用；
- `unavailable`：没有可用缓存或快照，或功能未配置。

`cache` 表示最快且正常的服务状态，不代表数据永久有效。缓存过期后，服务仍会按各业务既有规则尝试实时刷新，并在必要时回退快照。

## 返回示例

```json
{
  "schema_version": "query-observability.v1",
  "generated_at": "2026-07-29T06:00:00+00:00",
  "status": "degraded",
  "summary": {
    "live": 0,
    "cache": 2,
    "snapshot": 1,
    "stale": 1,
    "unavailable": 0
  },
  "sources": {
    "shard_data": {
      "name": "shard_data",
      "mode": "cache",
      "cache_active": true,
      "circuit": {
        "state": "closed",
        "consecutive_failures": 0,
        "open_remaining_seconds": 0,
        "in_flight": false,
        "last_error_class": "",
        "seconds_since_last_error": null,
        "seconds_since_last_success": 120.5
      },
      "snapshot": {
        "available": true,
        "status": "hit",
        "captured_at": "2026-07-29T05:58:00+00:00",
        "age_seconds": 120,
        "max_age_seconds": 604800,
        "last_success_at": "2026-07-29T05:58:00+00:00",
        "last_error_at": "",
        "last_error_class": ""
      }
    }
  },
  "caches": {
    "shard_entries": 3,
    "aram_payload_entries": 5,
    "aram_image_entries": 4
  }
}
```

完整字段由以下 Schema 固定：

```text
contracts/query-observability.v1.schema.json
```

## 海符榜聚合规则

OP.GG 上游客户端的内部 source ID 会包含 canonical 英雄标识。观测接口禁止返回这些 ID，因此只分为两类聚合：

- `augment_page`：强化符文页面；
- `build_page`：出装页面。

每类只返回：

- 已观察的数据源数量；
- 打开熔断的数量；
- 当前正在请求的数量；
- 最大连续失败次数；
- 最近错误类别集合；
- 距最近成功和最近失败的秒数。

每英雄 ARAM 快照也只返回汇总数量、有效数量、年龄范围和状态计数，不返回英雄名、alias、slug 或任何原始查询内容。

为避免异常目录造成过重扫描，单次最多检查 2048 个 ARAM 快照。达到上限时 `scan_truncated=true`。

## 安全边界

响应明确禁止包含：

- 公网上游 URL 或域名；
- 本地磁盘路径；
- Token、Cookie、密码和请求头；
- QQ 号码；
- 英雄查询词和动态 source ID；
- 原始异常正文；
- 快照正文和完整业务数据集；
- 查封号 provider 名称。

时间字段必须是合法 ISO 8601 时间，否则返回空字符串。错误类别必须匹配：

```text
^[A-Za-z][A-Za-z0-9_.-]{0,95}$
```

不符合格式的值统一变成：

```text
unexpected_error
```

## 与现有健康检查的关系

现有接口保持不变：

- `/livez`：仅检查进程是否存活；
- `/readyz`：检查 MySQL 和浏览器等必要依赖；
- `/health`：兼容旧管理端的综合状态；
- `/api/v1/operations/query-observability`：专门检查查询数据源、缓存、快照和熔断状态。

观测接口不会决定进程是否应被重启。公网数据源暂时失败但快照仍可用时，应显示 `degraded`，而不是让进程退出或进入重启循环。

## 部署验收

部署接口端版本后执行：

```powershell
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:5001/api/v1/operations/query-observability' `
  -Method Get | ConvertTo-Json -Depth 12
```

验收要求：

1. 返回 `schema_version=query-observability.v1`；
2. `sources` 包含 `shard_data`、`hero_catalog`、`aram`、`lolban`；
3. 正常查询一次后，对应缓存数量增加；
4. 人为阻断公网后，有快照的功能显示 `snapshot` 或 `stale`；
5. 快照缺失且上游失败时显示 `unavailable`；
6. 返回文本中不得出现 `http://`、`https://`、本地盘符、QQ 号、英雄查询词或凭据；
7. 查看接口不得产生新的公网请求日志。

## 当前发布边界

该接口只属于 `lolapisevers` 运维面。GroupGuard 不需要依赖此接口完成群消息查询；后续插件迁移只依赖 `groupguard-query-delivery.v1`。观测接口可供管理员、诊断脚本和未来 WebUI 状态页读取。
