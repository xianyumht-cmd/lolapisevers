# 全查询统一内网交付：发布验证检查点（2026-07-30）

## 结论

全查询服务端代码、GroupGuard 客户端代码和跨仓协议门禁已经完成最新全量验证，可以进入“先部署 Windows 接口”的发布阶段。

当前生产环境仍保持已验收的基线：

- Windows 服务提交：`8de85a855b8338c3a9a69cbb2a937cd0a6ef8b82`；
- SnowLuma 生产 dist：仅“查合集”迁移版本；
- 真人验收：`查合集 滑板鞋` 通过。

本检查点不表示新功能已经上线。

## 服务端验证

GitHub Actions：

- run：`30463744420`；
- job：`90636271068`；
- 结果：`success`；
- 覆盖：Python 单元测试、WebUI 生成、Node 语法、PowerShell 运维脚本语法。

隔离恢复验证：

- Python：227 项通过；
- 4 项跳过：仅 Windows PowerShell 专项，在 Linux 隔离主机不执行；
- `compileall`：通过；
- WebUI JavaScript 生成：通过；
- `node --check`：通过。

## GroupGuard 验证

最终客户端提交：`8a9d3ccea7663282ca6a9be8a23662bc589bf356`。

- 完整 CI run：`30470186595`，结果 `success`；
- 独立 Build run：`30470186613`，结果 `success`；
- `npm ci`：通过；
- `npm test`：通过；
- 部署 PowerShell 语法：通过；
- `npm run build:snowluma`：通过；
- 跨仓协议模拟：通过；
- 全查询客户端边界扫描：通过。

最终 CI 修复了两个真实兼容问题：

1. 协议版本不支持时恢复稳定错误码 `delivery_protocol_unsupported`；
2. 内网地址识别补充 IPv6 ULA 与链路本地范围，例如 `fd00::1`、`fe80::1`。

没有弱化测试或绕过门禁。

## 已验证范围

查询：

- `shard`：查合集；
- `aram`：海符榜；
- `lolban`：查封号；
- `battle`：查战绩；
- `hidden`：查隐藏；
- `video`：我要看；
- `scammer`：查骗子；
- `peer`：查同行；
- `dynamic`：动态查询。

共享写入：

- `scammer_report`：举报骗子；
- `peer_report`：举报同行。

风险库数据迁移状态：`skipped_empty_source`。操作员确认 ARM 本地没有骗子/同行业务数据，Windows 接口从空库开始。

## 发布顺序

```text
生成固定提交的 Windows 离线安全部署包
→ 部署 Windows 接口
→ 直接调用 query/report 协议验收
→ 交付最终 GroupGuard dist
→ 替换 SnowLuma dist
→ 群内完整命令矩阵验收
→ 更新生产检查点
→ 再决定是否合并 Draft PR
```

## 禁止事项

- 不得先替换最终 SnowLuma dist；
- 不得逐功能中间部署；
- 不得删除当前生产回滚备份；
- 不得在接口失败时恢复插件公网 fallback；
- 不得在生产验收前合并 PR #19 或 GroupGuard PR #17。
