# 全查询迁移下一对话交接（2026-07-30 03:38 +08:00）

## 读取顺序

新对话开始后依次读取：

1. 本文件；
2. `docs/plans/ALL_QUERY_DELIVERY_HUB_20260729.json`；
3. `docs/checkpoints/ALL_QUERY_RELEASE_VERIFICATION_20260730.md`；
4. GroupGuard 对应交接：`onebot-plugin-groupguard/docs/checkpoints/ALL_QUERY_NEXT_CHAT_HANDOFF_20260730.md`；
5. 两个 Draft PR：
   - `xianyumht-cmd/lolapisevers#19`
   - `xianyumht-cmd/groupguard-system#17`

## 总目标

所有跨群共享查询的业务逻辑、Provider、公网请求、业务解析、格式化、图片生成、缓存、重试、降级和共享数据均归 Windows `lolapisevers` 内网接口。

SnowLuma/GroupGuard 仅负责：

- 命令识别；
- 群权限、开关和限流；
- 提取最小参数；
- 请求 Windows 内网 `query/report`；
- 严格验证 `groupguard-query-delivery.v1`；
- 发送接口返回的最终文本、图片或合并转发。

未来官方机器人复用同一协议，不复制业务逻辑。

## Windows 接口当前生产状态

已成功部署：

```text
commit: ba54d83d7dd8cdbbb213b7bf38264655d671f134
service: LOLDataSystem
port: 5001
```

部署输出明确：

```text
LAPI all-query hub deployment completed successfully.
INTERFACE DEPLOYMENT SUCCEEDED.
```

部署备份：

```text
D:\project2\lolapisevers.deploy-backups\20260730-004927-lapi-all-query-hub
```

部署验证报告：

```text
D:\project2\lolapisevers.deploy-backups\20260730-004927-lapi-all-query-hub\verification-report.json
```

### 真实协议验收

用户已在 Windows PowerShell 直接请求：

```text
POST http://127.0.0.1:5001/api/v1/groupguard/query
feature=shard
hero=滑板鞋
```

返回：

```text
protocol=groupguard-query-delivery.v1
ok=true
feature=shard
source=live
hero alias=Kalista
hero name=复仇之矛
hero title=卡莉丝塔
```

结论：Windows 接口生产部署和 `shard` 真实协议验收均通过。

## Provider 迁移当前状态

ARM 实际检查结果：

```json
{
  "video_provider_count": 3,
  "video_categories": ["搞笑", "热门", "跳舞"],
  "risk_provider_count": 1,
  "dynamic_command_count": 1,
  "dynamic_http_count": 1,
  "dynamic_http_ids": ["custom.lolban.query.lolmap.template"]
}
```

Provider V2 迁移已成功：

- 自动恢复 V1 未完成迁移；
- 3 个视频 Provider 写入 Windows 环境；
- 1 个风险 Provider 写入 Windows 环境；
- 自定义动态 HTTP 命令迁为接口 Provider；
- 默认动态 Provider + 自定义 Provider 共 4 个；
- `LOLDataSystem` `/livez` 和 `/health` 通过；
- 风险查询冒烟测试通过；
- ARM 配置未修改；
- GroupGuard dist 未替换。

Provider 迁移备份：

```text
D:\project2\lolapisevers.provider-backups\20260730-033500-all-query-provider-migration
```

迁移日志：

```text
D:\project2\lolapisevers.provider-logs\20260730-033439-provider-migration-v2.log
```

### 视频诊断结果

三个旧视频 Provider 均不可用：

- `搞笑`：HTTP 502；
- `热门`：HTTP 502；
- `跳舞`：SSL 网络错误；
- 可用数量：0。

诊断报告：

```text
D:\project2\lolapisevers.provider-logs\20260730-033756-video-provider-diagnosis.json
```

## 用户最新决策（必须执行）

用户明确决定：

```text
“搞笑、热门、跳舞”三个 Provider 无关紧要，整个“我要看”视频查询功能不要了。
```

因此下一步不是继续修视频 Provider，而是彻底移除视频功能：

- 接口端移除 `feature=video` 正式路由和发布范围；
- GroupGuard 移除 `我要看` 命令插件和正式注册；
- 删除视频迁移要求、测试和文档范围；
- Windows Provider 环境中移除 `QUERY_VIDEO_PROVIDERS_JSON`，但保留风险 Provider；
- ARM 旧 `videoApiTemplates` 可在最终客户端部署成功后清理；
- 不得恢复视频公网 Provider 或 fallback。

## 重要：旧最终 dist 已作废

此前封存的 GroupGuard dist：

```text
groupguard-all-query-dist-SEALED-029118346ada.zip
commit: 029118346adaa9232aeceeb283f5d243a407dc95
```

该版本包含 `我要看/video`，因用户已取消视频功能，**禁止部署，视为作废产物**。

必须在移除视频功能、两仓 CI 全通过后重新生成最终 dist。

## GroupGuard 当前生产状态

ARM：

```text
host: 192.168.3.89
container: groupguard-snowluma
host app: /mnt/sda1/groupguard/app
container app: /app
runtime: node dist/snowluma-service.mjs
```

生产 dist 仍是此前仅完成并验收“查合集”的版本。

ARM 配置和 dist 在本轮 Provider 迁移中均未修改。

## 两个 Draft PR

API：

```text
PR #19
branch: feat/all-query-delivery-hub-20260729
current head before video-removal work: 1fb82f652e64346cc35b211aa0fd2460be59c6f0
state: Draft / Open / Unmerged
```

GroupGuard：

```text
PR #17
branch: feat/all-query-intranet-client-20260729
current head before video-removal work: 48b7a0491b5dfac541e01789f2da9d25bd343e25
state: Draft / Open / Unmerged
```

生产验收前禁止合并。

## 下一对话严格执行顺序

### 1. API 删除视频功能

审查并修改：

- `routers/groupguard_delivery.py`
- `services/video_query_service.py`
- `tests/test_video_query_service.py`
- 相关协议/路由测试
- API 计划、架构、检查点和 PR 描述

要求：

- `feature=video` 不再作为正式支持功能；
- 不影响 `dynamic` 中已有 `video.info` 动态示例，需明确判断：用户取消的是 `我要看` 分类视频功能；若动态 `video.info` 也没有实际用途，优先一并删除并记录；不得擅自保留无用视频功能。

### 2. Windows 配置清理

生成安全小补丁或一键脚本：

- 备份 `ops/app_env.local.ps1`；
- 仅移除 `QUERY_VIDEO_PROVIDERS_JSON`；
- 保留 `QUERY_SCAMMER_PROVIDERS_JSON`；
- 保留 `config/dynamic-query-providers.json` 中自定义 `custom.lolban.query.lolmap.template`；
- 若决定删除默认 `video.info`，同步从动态 Provider 目录删除；
- 重启 `LOLDataSystem`；
- 验证 `/livez`、`/health`、`shard`、`scammer` 和自定义动态命令；
- 失败自动回滚。

### 3. GroupGuard 删除“我要看”

审查并修改：

- 视频命令插件文件；
- `src/commands.ts` 注册；
- 命令门禁；
- 全查询边界门禁；
- 文档、计划和 PR 描述。

正式触发器中不得再出现 `我要看`。

### 4. 全量验证

API：

- Python 全量测试；
- WebUI 生成；
- Node syntax；
- PowerShell 语法；
- 新增“video feature 不再支持”的测试。

GroupGuard：

- `npm ci`；
- `npm test`；
- `npm run build:snowluma`；
- 跨仓协议模拟；
- 全查询边界门禁。

不得通过删除断言或跳过测试规避失败。

### 5. 重新发布

顺序：

```text
API 视频移除小版本部署包
→ Windows 部署与协议验收
→ 重新生成无视频 GroupGuard dist
→ ARM 替换一次 dist
→ 群内完整查询矩阵验收
→ 清理 ARM 旧视频配置和不可达旧查询代码
→ 再决定合并 PR
```

## 需要保留的功能

继续保留并完成：

- `shard` / 查合集；
- `aram` / 海符榜；
- `lolban` / 查封号；
- `battle` / 查战绩；
- `hidden` / 查隐藏；
- `scammer` / 查骗子；
- `peer` / 查同行；
- `scammer_report` / 举报骗子；
- `peer_report` / 举报同行；
- 自定义动态命令 `custom.lolban.query.lolmap.template`；
- 未来官方机器人渠道无关客户端。

## 禁止事项

- 不部署旧封存 dist；
- 不恢复 `我要看`；
- 不继续修三个旧视频 Provider；
- 不让 SnowLuma 重新访问公网业务 Provider；
- 不手工合并两个 Draft PR；
- 不删除 Windows/ARM 回滚备份；
- 不覆盖当前生产“查合集可用”回滚基线，直到新最终版本群内验收通过。

## 2026-07-30 API 视频移除代码阶段完成

已完成并由一次性工作流全量验证后提交：

- 删除正式 `video/我要看` 路由别名；
- 删除 `services/video_query_service.py`；
- 删除默认动态 Provider `video.info`；
- 将原视频正向测试替换为“视频功能必须不受支持”的退役门禁；
- 新增 Windows 配置清理脚本，仅移除 `QUERY_VIDEO_PROVIDERS_JSON`，保留风险与自定义动态 Provider；
- 旧含视频 dist 继续保持作废和禁止部署。

下一步：生成固定提交的 API 无视频离线安全部署包，部署 Windows，运行 shard/scammer/custom dynamic/health 验收，再进入 GroupGuard 无视频最终 dist 构建。
