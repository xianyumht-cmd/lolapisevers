# 跨仓查询协议发布门禁

## 范围

本门禁同时固定两个协议：

- `groupguard-query-delivery.v1`：接口端返回可直接下发的文字、图片、合并转发或用户可见错误；
- `query-observability.v1`：接口端返回不含敏感信息的查询链路运行状态。

对应消费者为 `xianyumht-cmd/groupguard-system`。

## 固定夹具

规范目录：

```text
contracts/fixtures/groupguard-query-contracts/
```

包含：

- `delivery-success-text.json`；
- `delivery-success-image.json`；
- `delivery-success-forward.json`；
- `delivery-error-retryable.json`；
- `observability-degraded.json`；
- `manifest.json`。

`manifest.json` 固定服务实现提交：

```text
7764dbec4854a7d39a194f6ec1802f0e8902ea9e
```

每个夹具均使用排序键、无多余空白的 canonical JSON 计算 SHA-256。整数值必须写成 JSON 整数，避免 Python 的 `0.0` 与 JavaScript 的 `0` 产生跨语言哈希差异。

## 服务端发布门禁

`tests/test_cross_repository_contract_gate.py` 必须验证：

1. 清单与全部夹具 SHA-256 一致；
2. 下发协议顶层字段、消息段字段和数量限制没有漂移；
3. 图片 Base64 可以严格解码，字节数与 SHA-256 一致；
4. 固定文字、图片和错误样本与正式 builder 输出一致；
5. 观测样本不含 URL、路径、Token、Cookie、QQ 或动态英雄标识；
6. 首次实时查询能够写入持久化快照；
7. 创建新服务上下文模拟重启后，公共网络完全不可达时仍能读取快照；
8. 恢复结果仍能生成合法的 `groupguard-query-delivery.v1` 最终下发内容。

该测试不访问真实公网，所有上游结果由本地假客户端注入。

## GroupGuard 消费门禁

GroupGuard 仓保存同一份清单和夹具，并要求：

- 未知协议或未知字段必须拒绝；
- 图片必须重新校验字节数和 SHA-256；
- 只允许 loopback、RFC1918、链路本地、私有 IPv6、`.local` 或单标签内网主机；
- 请求固定发送到 `POST /api/v1/groupguard/query`；
- 接口返回 503 或 `fetch failed` 时不得请求第二个地址；
- 新消费端源码不得出现 GitHub Raw、腾讯、OP.GG、lol2099 等公网数据源字面量。

## 发布顺序

1. 先完成并合并 `lolapisevers` 的堆叠 PR；
2. 在 Windows 内网电脑部署兼容服务版本；
3. 验证旧 GroupGuard 仍可工作；
4. 验证实时、快照、重启、断网和观测接口；
5. 再进入 GroupGuard 的真实命令迁移；
6. GroupGuard 迁移完成前，不删除旧服务接口。

## 当前边界

本门禁只证明服务契约和新 GroupGuard 消费端兼容。当前线上 GroupGuard 的 `查合集` 仍保留插件端公网抓取旧实现；该代码必须在后续 `GG-SHARD-001` 中删除，不能把本步骤误认为已完成插件迁移。
