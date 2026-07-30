# lolapisevers 内网查询服务强化执行计划（2026-07-28）

> 计划 ID：`GGK-INTRANET-QUERY-20260728`  
> 仓库角色：查询业务服务与唯一公网出口  
> 生产基线：`codex/production-integration-audit-20260726`

## 1. 审查结论

生产分支已经完成一部分基础建设：

- 战绩实时失败可回退 MySQL 快照；
- ARAM 已具备并发合并、条件请求和图片缓存优化；
- 封号已经统一 Provider 配置，并支持内存级 stale；
- 健康、构建信息和部署回滚能力已经增强。

但当前仍存在统一性缺口：

- `fetch_json_url()` 只有一次请求，没有重试和错误分类；
- 合集与英雄表只有内存缓存；
- ARAM 英雄表和业务结果没有持久化 LKG；
- 封号 LKG 重启后丢失；
- 服务尚未向 GroupGuard 返回统一的最终交付载荷；
- 查询依赖的 `live/cache/snapshot/stale/unavailable` 状态没有统一暴露。

本轮目标不是只修一次 `fetch failed`，而是建立可复用的持久化查询基础设施，避免后续同类故障逐项补洞。

## 2. 执行步骤

### LAPI-DOC-001：建立服务边界和执行计划

状态：`completed`

交付：

- `docs/architecture/INTRANET_QUERY_SERVICE_BOUNDARY.md`
- 本执行计划
- 同名机器可读 JSON 状态文件

### LAPI-SNAPSHOT-001：实现统一持久化快照组件

状态：`next`

目标：为合集、英雄表、ARAM 和封号提供统一的原子落盘、校验、恢复和陈旧时间管理。

建议新增：

```text
services/persistent_snapshot_store.py
```

最小接口：

```python
save(source_id, payload, metadata)
load(source_id, max_age_seconds)
record_refresh_error(source_id, error_class, message)
status(source_id)
```

要求：

- 临时文件 + fsync + 原子替换；
- schema_version 与 SHA-256；
- 损坏文件隔离备份；
- 每个 source 独立锁；
- 日志脱敏；
- 数据目录可配置；
- 运行时目录加入 `.gitignore`；
- 不把业务 TTL 和最大 stale age 混为一个值。

测试：

- 正常写入/读取；
- 并发写入；
- 中断写入不破坏旧快照；
- 哈希错误；
- JSON 损坏；
- schema 不兼容；
- 过期拒绝；
- Windows 原子替换行为。

### LAPI-UPSTREAM-001：实现统一上游请求客户端

状态：`planned`

目标：替代当前单次 `requests.get`，提供受控重试、条件请求和结构化错误。

建议新增：

```text
services/upstream_http_client.py
```

能力：

- connect/read timeout 分离；
- 有上限的重试和抖动退避；
- 429/部分 5xx 重试；
- ETag/Last-Modified；
- DNS/connect/read/TLS/HTTP/parse/schema 错误分类；
- source_id 日志；
- 不输出敏感完整 URL。

### LAPI-SHARD-001：强化合集与英雄基础数据

状态：`blocked`

依赖：`LAPI-SNAPSHOT-001`、`LAPI-UPSTREAM-001`

改动：

- 合集数据和英雄表分别持久化；
- 启动时加载最近成功快照；
- 上游刷新失败时继续使用受控快照；
- 两个上游独立刷新，避免一个失败破坏另一个已有数据；
- 只有在没有任何可接受快照时才返回不可用；
- 响应增加 `source`、`stale_age_seconds`、`upstream_status` 和 `warnings`；
- 英雄匹配、排序和图片生成继续由服务完成。

完成标准：

- Windows 断网和 GitHub Raw 超时时仍可查询已有英雄；
- 服务重启后不需要先访问公网即可处理查询；
- 快照超过最大年龄时明确拒绝或标记不可用；
- `查合集 滑板鞋`、中文称号、英文 alias 均通过。

### LAPI-ARAM-001：强化 ARAM/海符榜持久化降级

状态：`planned`

依赖：`LAPI-SNAPSHOT-001`、`LAPI-UPSTREAM-001`

改动：

- 英雄表复用统一快照；
- 每个 canonical alias 保存最近成功 ARAM 业务结果；
- OP.GG 失败时返回最大年龄内的 LKG；
- 辅助 build 数据失败不得破坏核心 augments；
- 保留 singleflight 和条件请求；
- 图片端点使用相同 payload，不重复抓取。

### LAPI-BAN-001：持久化封号 LKG

状态：`planned`

改动：

- 将 `_last_known` 从纯内存扩展为受控磁盘快照；
- 每个 QQ 保存最近成功结果、Provider 名称和时间；
- 重启后可恢复；
- `LOL_BAN_STALE_CACHE_SECONDS` 继续作为最大陈旧窗口；
- 响应不能把 stale 标为 live。

### LAPI-DELIVERY-001：新增最终交付协议

状态：`planned`

目标：让 GroupGuard 不再解析业务数据或决定图片/文本降级。

建议方案：

- 优先给现有接口增加 `output=delivery`；
- 内部复用同一查询服务和渲染器；
- 返回 `groupguard-query-delivery.v1`；
- 支持 `text`、`image_url`、`forward`、`none`；
- 图片 URL 必须是内网稳定地址；
- 用户提示、stale 说明和错误文案由服务生成。

覆盖接口：

- `/cross_query`
- `/shard_query`
- `/aram_augments`
- `/api/v2/lolban`

后续可在兼容稳定后评估统一 `/api/v3/query`，但不得在本轮同时复制两套业务逻辑。

### LAPI-OBS-001：依赖状态与管理页面

状态：`planned`

增加：

- 每个 source 的最后成功时间；
- 当前状态 `live/cache/snapshot/stale/unavailable`；
- 快照年龄；
- 最近错误类别；
- 连续失败次数；
- 熔断状态；
- 管理页面只显示脱敏信息。

`readyz` 应区分“完全不可服务”和“可用陈旧快照的降级服务”。

### LAPI-CONTRACT-001：测试与双仓契约

状态：`planned`

要求：

- 单元测试覆盖持久化、刷新和降级；
- fixture 覆盖交付协议；
- 双仓固定提交集成测试；
- 模拟 SnowLuma 无公网、Windows 有/无公网；
- 模拟服务重启；
- 模拟上游 429、500、超时、非 JSON 和结构变化；
- 验证旧插件在服务升级后仍可工作。

### LAPI-DEPLOY-001：先部署服务端

状态：`blocked`

依赖：上述代码和测试全部通过。

步骤：

1. 生成当前生产备份和构建信息；
2. 部署兼容版本；
3. 验证旧 GroupGuard 四类查询；
4. 验证快照目录和 ACL；
5. 断开公网上游或使用故障注入，验证 stale/snapshot；
6. 验证 build commit、livez、readyz 和依赖状态；
7. 保持观察窗口；
8. 通过后才允许迁移 GroupGuard。

## 3. 跨仓执行顺序

```text
LAPI-SNAPSHOT-001
  -> LAPI-UPSTREAM-001
  -> LAPI-SHARD-001
  -> LAPI-ARAM-001
  -> LAPI-BAN-001
  -> LAPI-DELIVERY-001
  -> LAPI-OBS-001
  -> LAPI-CONTRACT-001
  -> LAPI-DEPLOY-001
  -> GG-CLIENT-001
  -> GG-SHARD-001
  -> GG-LOL-UNIFY-001
```

## 4. 第一实施批次

第一批只做：

1. `LAPI-SNAPSHOT-001`
2. `LAPI-UPSTREAM-001`
3. `LAPI-SHARD-001`

理由：

- 直接解决本次查合集故障；
- 建立后续 ARAM/封号可复用基础；
- 不需要立即改 GroupGuard；
- 可以先部署服务端并保持旧插件兼容。

第一批验收完成后，再进入 `LAPI-DELIVERY-001` 和插件迁移。

## 5. 回滚与安全

- 新服务版本必须兼容旧插件接口。
- 快照文件属于运行时数据，禁止提交。
- Provider 凭据仍只存在于本机受限配置。
- 任何迁移不得使用 `git add .`。
- 发布前后都必须记录完整 commit 和构建清单。
- 回滚恢复完整版本、配置和数据结构，不跨版本拼接。

## 6. 下一步建议和指令

下一步执行：

```text
LAPI-SNAPSHOT-001
```

本地开发分支建议从生产基线创建：

```powershell
cd D:\project2\lolapisevers
git fetch origin
git checkout codex/production-integration-audit-20260726
git pull --ff-only origin codex/production-integration-audit-20260726
git checkout -b feat/persistent-query-snapshots-20260728
```

随后只实现快照组件和对应测试，不同时修改 GroupGuard。
