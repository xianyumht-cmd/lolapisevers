# ARAM 英雄平衡数据

## 目标

海符榜查询在保留原有 OP.GG 强化、出装、召唤师技能和技能顺序结果的同时，补充英雄在 ARAM: Mayhem 模式中的专属 Buff / Debuff，并由接口端统一绘制到最终图片。

GroupGuard 仍只消费 `/api/v1/groupguard/query` 的最终图片交付，不解析第三方网页字段。

## 数据流

```text
英雄查询词
  -> 现有英雄目录归一化
  -> 原海符榜 OP.GG 查询
  -> ARAM Mayhem 英雄平衡页（可选增强）
  -> Riot Data Dragon 当前版本校验
  -> 标准化 balance 数据 / 旧版本保护
  -> 图片缓存键包含 balance
  -> 英雄平衡修正面板
  -> /aram_augments 或 GroupGuard 最终图片
```

平衡数据是可选增强：它失败时不能使原海符榜查询失败，也不能阻断原图片交付。

## 标准字段

`balance` 对象包含：

- `status`: `ok | snapshot | syncing | unverified | unavailable`；
- `provider`: 当前为 `arammayhem`；
- `patch`: 当前用于展示/校验的版本；
- `page_patch`: ARAM Mayhem 英雄页自身标注的版本；
- `current_patch_verified`: 是否已确认页面/快照与当前 Riot 版本一致；
- `changes`: 英雄专属修正数组；
- `summary`: 适合文字展示的简短摘要；
- `stale`: 是否使用持久化快照；
- `snapshot_age_seconds`: 快照年龄；
- `error_class`: 降级或保护原因类别。

每个 `changes` 元素包含：

- `key`: 稳定机器字段；
- `label`: 中文字段名；
- `value`: 上游原始数值表达；
- `direction`: `buff | debuff | neutral`。

当前识别字段与 FACM 保持一致：

- 造成伤害；
- 承受伤害；
- 攻击速度；
- 技能急速 / 冷却缩减；
- 治疗；
- 护盾；
- 韧性；
- 对小兵伤害。

`Damage Taken` 的增减方向与普通增益数值相反：承受伤害降低属于 Buff，承受伤害提高属于 Debuff。

## 版本一致性保护

ARAM Mayhem 英雄页可能晚于 Riot 当前版本更新。为避免把上一版本数值画成“当前 Buff / Debuff”，接口会额外读取 Riot Data Dragon 的当前版本并进行版本校验。

Data Dragon 的现代客户端版本号仍可能采用 `16.15.x` 这类编号，而 Riot 公共补丁标签为 `26.15`。接口会将现代 Data Dragon major 映射到对应公共补丁标签后再比较。

规则：

- 页面 Patch 与当前 Riot Patch 一致：允许展示并持久化该英雄平衡值；
- 页面 Patch 落后：返回 `status=syncing`，清空 `changes`，图片显示“同步中”，明确隐藏旧 Buff / Debuff；
- 实时页面失败但存在快照：只有快照 Patch 与当前 Riot Patch 一致时才允许回退；
- 快照也属于旧版本：同样进入 `syncing`，不展示旧值；
- 无法取得当前 Riot Patch 时：不伪造已校验状态，页面有 Patch 时仍保留来源信息；页面 Patch 缺失则标记 `unverified`。

这与 FACM 的原则一致：宁可在版本切换窗口暂时不展示完整平衡数值，也不把旧版本数值冒充当前数据。

## 稳定性与缓存

- 平衡页和 Riot 版本查询都使用共享 `UpstreamHttpClient`，统一接受超时、熔断和错误分类约束；
- HTTP 观测使用固定 source id `aram-balance-page` 与 `riot-ddragon-versions`，不把英雄 alias/slug 暴露为上游状态 key；
- 每英雄仅在版本允许展示时写入独立持久化快照；
- 实时平衡页失败时，可在 `ARAM_SNAPSHOT_MAX_AGE_SECONDS` 范围内使用同版本最近有效快照；
- 无可用快照时返回 `balance.status=unavailable`，原海符榜继续正常返回；
- 进程内使用 canonical alias 缓存平衡结果，避免短时间重复抓取；
- Riot 当前版本也使用短期进程缓存，避免每个英雄重复请求版本列表；
- ARAM 图片 ETag / 缓存摘要包含 `balance`，版本或平衡值变化会自动生成新的图片缓存版本。

## 图片行为

在原英雄头部之后插入“英雄平衡修正 · Buff / Debuff”面板：

- Buff：绿色强调；
- Debuff：红色强调；
- Neutral：青色强调；
- 已通过当前版本校验时标记“已校验”；
- 快照数据明确标记“快照”；
- 页面版本落后时标记“同步中”，不绘制旧数值；
- 无法确认页面版本时标记“未校验”；
- 最多展示 8 个修正，防止图片无限增高；
- 平衡数据完全不可用时保持原海符榜图片，不显示错误占位面板。

## 兼容性

- `GET /aram_augments?hero=...&output=image`：图片增加平衡面板；
- `GET /aram_augments?hero=...&output=json`：增加 `balance` 对象；
- `POST /api/v1/groupguard/query` 的 `feature=aram`：最终图片在渲染前自动补充 `balance`，无需修改 GroupGuard；
- 原强化、出装、英雄目录、持久化 ARAM 成品快照与 GroupGuard 协议字段保持兼容。
