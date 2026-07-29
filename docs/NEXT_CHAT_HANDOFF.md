# 下一聊天交接：LAPI-DEPLOY-001 生产恢复

## 开场必须先做

读取：

- `docs/CHAT_CHECKPOINT_LAPI_DEPLOY_001_20260729.md`
- `docs/EXECUTION_CHECKPOINT_LAPI_DEPLOY_001_20260729.json`
- 本文件

然后等待并分析用户上传的：

- recovery diagnostics v2 完整窗口输出；
- `diagnostics-YYYYMMDD-HHMMSS.zip`。

## 当前生产状态

- `D:\project2\lolapisevers` 当前最后确认 HEAD：`bd2d92996f8c7af4e6fd51f021f1546bda250a8a`
- `LOLDataSystem` 在服务管理器中显示 Running
- `http://127.0.0.1:5001/livez` 不可达
- 生产 API 当前视为不可用
- 本次备份必须保留：
  `D:\project2\lolapisevers.deploy-backups\20260729-163439-lapi-query-hardening`

## 禁止事项

- 不运行 v1-v5 部署包；
- 不创建或执行新的部署包；
- 不合并 PR #17；
- 不合并 PR #8-#16；
- 不启动 `GG-CLIENT-001`；
- 不删除备份目录；
- 不在读取 diagnostics ZIP 前猜测服务启动根因。

## 已确认问题

v5 已真实停止服务并切到目标提交，但全量测试从错误 cwd 执行，导致大量项目内模块无法导入。自动回滚到 `bd2d929...` 后，Windows 服务状态虽然为 Running，5001 仍未恢复。

服务启动失败的准确原因尚未确认，必须根据 direct-run stderr、服务配置和日志判断。

## 下一步判断树

### A. 直接启动成功，Windows 服务启动失败

- 保留脚本建立的临时直接运行模式；
- Windows 服务保持停止，避免端口冲突；
- 验证 `/livez`、`/health`、5001 局域网访问；
- 再修复 Windows 服务配置或服务账户环境。

### B. 直接启动也失败

- 读取 `11-direct-run.stderr.log`；
- 优先修复最早的致命错误；
- 只制作恢复修复，不继续新版本部署。

### C. Windows 服务和直接启动均成功

- 确认 5001 稳定；
- 标记生产恢复完成；
- 再重构发布流程为 worktree 预检，禁止在停服务后首次跑全量测试。

## 恢复完成后的发布重构原则

- 目标提交在临时 `git worktree` 中测试；
- 测试 cwd 和 `PYTHONPATH` 指向目标 worktree；
- 全部测试与 build-info 校验通过后才停止生产；
- HTTP 健康检查是最终依据，不能仅相信 Windows 服务状态；
- 回滚失败必须自动收集服务配置和日志，并提供直接启动兜底。

## 用户新聊天可直接发送

```text
继续 LAPI-DEPLOY-001 生产恢复任务。按仓库 docs/CHAT_CHECKPOINT_LAPI_DEPLOY_001_20260729.md、docs/EXECUTION_CHECKPOINT_LAPI_DEPLOY_001_20260729.json 和 docs/NEXT_CHAT_HANDOFF.md 继续。我会把 recovery diagnostics v2 的完整窗口输出和 diagnostics ZIP 一起上传。先恢复 5001，禁止继续部署。
```
