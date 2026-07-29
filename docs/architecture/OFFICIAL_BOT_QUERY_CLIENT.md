# 官方机器人查询适配边界

## 定位

官方机器人是合规展示、品牌入口和辅助查询渠道，不是 GroupGuard 商业主线的运行依赖。

- 普通 QQ 号 + SnowLuma/GroupGuard 仍可独立运行；
- 官方机器人不可成为 SnowLuma 查询成功的前置条件；
- 官方机器人和 SnowLuma 消费同一套 Windows 内网接口与交付协议；
- 任何新查询功能必须先在接口端实现，再由不同渠道增加轻量适配器。

## 统一接口

查询：

```text
POST /api/v1/groupguard/query
```

共享写入：

```text
POST /api/v1/groupguard/report
```

协议：

```text
groupguard-query-delivery.v1
```

官方机器人客户端只能提交：

- `feature`；
- 原始、最小化的 `parameters`；
- 渠道支持的 `capabilities`；
- `preferred`；
- 可追踪或幂等的 `request_id`；
- 不含凭据的客户端名称。

## 官方机器人允许承担的职责

1. 识别官方平台事件和命令；
2. 获取发送者、会话和消息 ID；
3. 执行官方平台自身的权限、频率与内容规则；
4. 将命令转换为接口 `feature + parameters`；
5. 请求 Windows 内网接口；
6. 严格验证协议、功能名、图片 Base64、字节数和 SHA-256；
7. 将文本、图片或多节点结果转换为官方机器人 SDK 的发送调用；
8. 记录渠道级请求 ID、发送结果和安全错误码。

## 官方机器人禁止承担的职责

- 保存业务 Provider URL、Cookie、Token、账号或密码；
- 直接访问 GitHub Raw、腾讯英雄表、LOL 查询站、视频 Provider、骗子库 Provider 等公网业务源；
- 解析上游 HTML 或业务 JSON；
- 匹配英雄别名、计算榜单、格式化战绩或判断风险命中；
- 决定图片生成、文本降级、缓存、重试、熔断或最近有效快照；
- 在内网接口失败时改走公网备用接口；
- 维护一份与 Windows 接口不一致的业务数据库。

## 功能映射示例

| 官方命令 | feature | parameters |
|---|---|---|
| 查合集 滑板鞋 | `shard` | `{"hero":"滑板鞋"}` |
| 海符榜 亚索 | `aram` | `{"hero":"亚索"}` |
| 查封号 123456789 | `lolban` | `{"qq":"123456789"}` |
| 查战绩 玩家#标签 | `battle` | `{"name":"玩家#标签"}` |
| 查隐藏 玩家 1 | `hidden` | `{"name":"玩家","region":"1"}` |
| 我要看 热门 | `video` | `{"category":"热门"}` |
| 查骗子 123456789 | `scammer` | `{"identifier_type":"qq","identifier":"123456789"}` |
| 查同行 wx_example | `peer` | `{"identifier_type":"wechat","identifier":"wx_example"}` |
| 点歌 晴天 | `dynamic` | `{"command_id":"music.search","keyword":"晴天"}` |
| 举报骗子 123456789 收款后失联 | `scammer_report` | 发送到 `/report`，并使用官方消息 ID 作为稳定 `request_id` |

## 参考客户端

仓库提供：

```text
clients/channel_neutral_query_client.py
```

该客户端：

- 只允许连接内网或本机地址；
- 不包含任何平台 SDK；
- 支持 query/report；
- 严格解析统一协议；
- 验证图片 MIME、Base64、字节数和 SHA-256；
- 将合并转发保留为渠道无关节点；
- 将服务端错误限制为安全错误码、用户提示和重试建议。

官方机器人项目应在它外面新增一层平台适配器，而不是复制接口业务实现。

## 发布顺序

```text
接口实现与测试
→ Windows 接口部署和直接协议验收
→ SnowLuma/GroupGuard 客户端部署和群内验收
→ 官方机器人适配器部署和官方平台验收
```

任何客户端都不能先于对应服务端 feature 进入生产。
