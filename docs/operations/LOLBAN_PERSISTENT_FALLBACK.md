# 查封号持久化最近成功结果

## 目标

查封号继续按配置顺序访问多个上游提供方，但最近一次成功结果不再只保存在进程内存中。

服务会把受限的最近成功结果集合保存为：

```text
data/upstream_snapshots/lolban-last-known-v1.json
```

该文件由 `PersistentSnapshotStore` 原子写入并带 SHA-256 内容校验。目录可以通过 `UPSTREAM_SNAPSHOT_DIR` 修改。

## 数据边界

持久化文件只包含接口已经清洗过的业务结果：

- QQ 号码；
- 正常或封禁状态；
- 封禁时间；
- 剩余时间或解封说明；
- 安全的提供方名称；
- 每次尝试的成功状态、异常类别和耗时。

不会保存：

- 上游完整 URL；
- 请求头；
- Cookie、Token、密码；
- 表单内容；
- 原始异常正文；
- 上游广告或联系方式。

恢复时会再次验证 QQ、状态和消息安全性。QQ 不匹配、状态未知、包含网址或广告字样的条目会被忽略。

## 查询顺序

1. 命中正常或封禁短缓存时返回 `source=cache`；
2. 依次请求已配置上游；
3. 任一上游成功时返回 `source=live`，更新短缓存和持久化 LKG；
4. 所有上游失败时，检查内存中的最近成功结果；
5. 服务刚重启时，内存 LKG 来自持久化快照；
6. 有效 LKG 返回 `source=stale`；
7. 没有有效 LKG 时返回 HTTP 503。

持久化不会改变实时结果判断。磁盘写入失败时，实时查询仍然成功，只会在响应和健康状态中记录写入错误类别。

## 时间与容量限制

默认配置：

```powershell
$env:LOL_BAN_STALE_CACHE_SECONDS = "86400"
$env:LOL_BAN_MAX_STALE_ENTRIES = "1024"
$env:LOL_BAN_SNAPSHOT_ENABLED = "1"
```

含义：

- 最近成功结果最多使用 24 小时；
- 内存和持久化快照最多保留 1024 个 QQ；
- 超过容量时删除最早使用的条目；
- `LOL_BAN_STALE_CACHE_SECONDS=0` 时不提供 stale 回退；
- `LOL_BAN_SNAPSHOT_ENABLED=0` 时只保留原有内存 LKG。

## 返回字段

原有接口保持不变：

```http
GET /lolban?qq=2621735529&output=json
GET /api/v2/lolban?qq=2621735529&output=text
```

持久化恢复后的结果仍使用：

```json
{
  "source": "stale",
  "fallback_reason": "all_providers_failed",
  "stale_origin": "persistent_snapshot",
  "stale_age_seconds": 120
}
```

同一进程内的 LKG 回退使用：

```json
{
  "stale_origin": "memory"
}
```

健康状态新增：

- `persistent_snapshot_enabled`；
- `persistent_snapshot_status`；
- `persistent_snapshot_restored_entries`；
- `persistent_snapshot_write_error_class`。

## 发布验收

部署前必须验证：

1. 上游正常时查询返回 `source=live`；
2. 快照文件生成且条目数量不超过配置上限；
3. 重启服务后让全部上游不可用，已查询 QQ 返回 `source=stale`；
4. 返回 `stale_origin=persistent_snapshot`；
5. 超过 stale 时间后不再返回旧状态；
6. 损坏快照被隔离为 `.bad` 文件；
7. 磁盘只读或空间不足时，实时查询仍然成功；
8. 旧的 text/json/compat 接口和字段继续可用。

## 生产顺序

本功能必须随 `lolapisevers` 服务端版本先发布。GroupGuard 无需为此步骤修改，因为插件原本就通过内网接口执行查封号。
