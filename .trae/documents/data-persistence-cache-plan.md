# 数据持久化与缓存实施计划

## Summary
- 目标：仅在接口端（不改插件）为 `cross_query` 增加“结果持久化 + 5分钟缓存 + 上游失败回退快照”，并在返回中新增“最后上线时间（格式：`%Y年%m月%d日%H时`）”。
- 成功标准：
  - 同一 `name+region` 在 5 分钟内重复请求命中缓存；
  - 上游失败时可返回最近一次成功快照并显式标注；
  - 返回结构保持现有字段兼容，并新增 `last_online_time`；
  - 通过接口级联调验证（正常、命中缓存、上游失败回退三类场景）。

## Current State Analysis
- 现有跨区主链路在 [app.py](file:///d:/project2/lolapisevers/app.py)：
  - `cross_query` 调用 `So1Client.query_summoner` 后拼装 `pretty/raw` 返回；
  - 当前没有跨区结果的数据库落库，也没有跨区请求缓存与快照回退逻辑；
  - `query` 已有 `TTLCache` 的本地缓存思路（`collect_cache`），可复用同类模式。
- 数据层在 [db.py](file:///d:/project2/lolapisevers/db.py)：
  - 现有表偏向 LCU 比赛数据（summoners/matches/match_participants）；
  - 尚无针对跨区 `cross_query` 的“按 `name+region` 存储原始/可视化结果”表。
- 缓存组件在 [cache.py](file:///d:/project2/lolapisevers/cache.py)：
  - 已有线程安全 TTLCache，可直接用于跨区缓存（5分钟）。

## Proposed Changes

### 1) 数据库层：新增跨区快照表与读写接口
- 文件：`d:/project2/lolapisevers/db.py`
- 变更：
  - 新增表 `cross_query_snapshots`（若不存在则自动建表）：
    - `id` 自增主键
    - `query_name`（原始入参名）
    - `region`（区服代码或名称）
    - `display_name`（识别后的展示名）
    - `payload_pretty`（JSON 文本）
    - `payload_raw`（JSON 文本，可选）
    - `is_success`（是否成功快照）
    - `updated_at`（更新时间）
    - 唯一键：`(query_name, region)`（支持 UPSERT）
  - 新增方法：
    - `upsert_cross_snapshot(name, region, display_name, payload_pretty, payload_raw, is_success, updated_at)`
    - `get_cross_snapshot(name, region)`（返回最近快照）
- 目的：
  - 支撑失败回退与重启后可恢复的结果持久化。

### 2) 接口层：cross_query 增加缓存/持久化/回退
- 文件：`d:/project2/lolapisevers/app.py`
- 变更：
  - 新增 `cross_cache = TTLCache(ttl_seconds=300)`，键：`cross:{name}:{region}:{output}`。
  - 在 `cross_query` 中加入处理顺序：
    1. 先查内存缓存（命中直接返回，带 `source=cache`）；
    2. 未命中则请求上游 so1；
    3. 上游成功：
       - 生成 `pretty/raw` 返回；
       - 写入内存缓存；
       - 调用 DB `upsert_cross_snapshot` 持久化；
       - 返回 `source=live`。
    4. 上游失败：
       - 查询 DB 快照；
       - 若有成功快照则返回并标注 `source=snapshot`、`is_stale=true`；
       - 若无快照则按现状报错（503）。
  - 在 `pretty` 返回新增：
    - `last_online_time`：优先从基础信息可用时间字段推导，格式 `%Y年%m月%d日%H时`；
    - 无法推导时留空字符串（不抛错）。
  - 在 `raw` 返回也补充：
    - `source`、`is_stale`、`snapshot_updated_at`（如命中快照）。
- 目的：
  - 不改插件前提下提升稳定性与可用性，并满足“最后上线时间”需求。

### 3) 可靠性与兼容细节
- 文件：`d:/project2/lolapisevers/app.py`, `d:/project2/lolapisevers/db.py`
- 变更：
  - 统一 JSON 序列化容错（datetime、None、安全转换）；
  - `region` 为空时使用稳定默认值参与缓存键与快照键，避免键漂移；
  - 回退快照时保持现有字段结构，新增字段只增不改（插件无感兼容）。

## Assumptions & Decisions
- 已确认决策：
  - 覆盖范围：仅 `cross_query`；
  - 缓存 TTL：5 分钟；
  - 上游失败策略：返回最近成功快照并标注；
  - 不改插件，仅改接口端；
  - 返回新增字段：`last_online_time`（`%Y年%m月%d日%H时`）。
- 约束：
  - 需兼容当前服务与保活脚本运行方式；
  - 不引入额外外部中间件（如 Redis），先用现有 MySQL + 内存 TTL。

## Verification Steps
- 功能验证：
  1. 调用一次 `cross_query`（`output=pretty`）应 `source=live`，包含 `last_online_time` 字段；
  2. 5 分钟内重复同参调用应命中缓存（`source=cache`）；
  3. 人为制造上游失败（如临时断会话/异常）后调用，应命中快照（`source=snapshot`，`is_stale=true`）；
  4. `output=raw` 同样验证 live/cache/snapshot 三态返回字段。
- 数据验证：
  - 检查 `cross_query_snapshots` 中 UPSERT 更新行为是否正确；
  - 校验 `updated_at` 与返回 `snapshot_updated_at` 一致。
- 回归验证：
  - `query`、`hidden_query` 行为不变；
  - `npm` 插件侧无需改动即可正常展示。
