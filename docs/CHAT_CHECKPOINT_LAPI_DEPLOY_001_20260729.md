# LAPI-DEPLOY-001 新聊天交接检查点

更新时间：2026-07-29 16:56 +08:00

## 当前结论

`LAPI-DEPLOY-001` 尚未完成，当前阶段是 **生产恢复与故障诊断**，不是继续部署。

最后一次可确认的生产状态：

- 本地仓库：`D:\project2\lolapisevers`
- Git HEAD：`bd2d92996f8c7af4e6fd51f021f1546bda250a8a`
- Windows 服务：`LOLDataSystem` 显示为 Running
- 主接口：`http://127.0.0.1:5001/livez` 无法连接
- 结论：Windows 服务外壳存在，但主 API 子进程没有正常监听 5001
- 当前不得继续执行任何 v1-v5 部署包
- PR #17 继续保持 Draft，禁止合并

## 用户下一聊天会提供的材料

用户将在新聊天中上传：

1. `loldata-recovery-diagnose-v2-20260729` 的完整窗口输出；
2. 脚本生成的 `diagnostics-YYYYMMDD-HHMMSS.zip`。

新聊天收到材料后，应立即分析 ZIP 中的以下文件，不要先让用户执行其他命令：

- `00-summary-before.txt`
- `01-service-qc.txt`
- `02-service-queryex.txt`
- `10-direct-run.stdout.log`
- `11-direct-run.stderr.log`
- `12-direct-result.txt`
- `20-service-retest.txt`
- `30-temporary-direct.stdout.log`
- `31-temporary-direct.stderr.log`
- `32-temporary-direct-result.txt`
- `99-final-health.txt`
- 项目日志尾部副本

## 下一步唯一优先级

先恢复 5001，再继续任何发布工作。

处理顺序：

1. 判断 `ops\run_service.ps1` 直接启动是否成功；
2. 若直接启动成功、Windows 服务失败：保留临时直接模式，Windows 服务保持停止，先确认 `/livez` 和 `/health`；
3. 若直接启动也失败：根据 `direct-run.stderr.log` 修复真实启动错误；
4. 只有 5001 恢复并稳定后，才修订部署工具；
5. 不得在恢复完成前重新执行 v1-v5 或创建 v6 部署包。

## v5 实际执行结果

v5 是第一次真正进入生产切换：

1. 拉取发布分支成功；
2. 停止 `LOLDataSystem`；
3. checkout 到 `3d4e5d8af635705e33599f02bc7dc648d250568d`；
4. 依赖检查通过；
5. 全量测试失败；
6. 自动回滚到部署前 Git HEAD `bd2d92996f8c7af4e6fd51f021f1546bda250a8a`；
7. 回滚后的 Windows 服务未能恢复 5001；
8. 自动回滚最终失败。

本次备份目录：

```text
D:\project2\lolapisevers.deploy-backups\20260729-163439-lapi-query-hardening
```

必须保留，不得删除。

## 已确认的测试失败原因

部署脚本从临时目录调用：

```text
python -m unittest discover -s D:\project2\lolapisevers\tests
```

但没有把工作目录切换到项目根目录，导致 30 个本地模块导入失败，包括：

- `cache`
- `services`
- `routers`
- `core`
- `renderers`
- `lanzou_update_push_api_server`

这不是业务测试断言失败，而是部署脚本的测试执行目录错误。

后续正式修复应至少做到：

- 测试进程 cwd 固定为项目根目录；
- 或显式设置 `PYTHONPATH` 为目标源码根目录；
- 更好的方案是在独立 `git worktree` 中预先完成目标提交的全部测试，测试全部通过后才停止线上服务；
- 不应再次在服务已停止后才第一次运行目标提交全量测试。

## 尚未确认的服务启动根因

紧急恢复脚本已再次 checkout `bd2d929...`、恢复备份文件并启动 Windows 服务，但 5001 仍不可达。

目前只能确认：

- Windows 服务状态显示 Running；
- 主 API 没有正常监听 5001；
- 真实原因必须以 recovery diagnostics v2 的直接启动 stderr、服务配置和日志为准；
- 不得继续猜测为 build-info、Python、NSSM、端口或配置问题。

## 部署包历史

- v1：UTF-8 文本重写导致 PowerShell 语法损坏，停服务前失败；
- v2：Windows PowerShell 5.1 无 BOM 解析问题，停服务前失败；
- v3：Git stderr 被升级为 `NativeCommandError`，停服务前失败；
- v4：PowerShell 5.1 混合输出/泛型集合触发 `Argument types do not match`，停服务前失败；
- v5：兼容问题已越过，真实进入部署；因测试 cwd 错误失败，回滚后服务未恢复。

## 仓库与 PR 状态

- 仓库：`xianyumht-cmd/lolapisevers`
- 发布分支：`release/lapi-query-hardening-20260729`
- Draft PR：#17
- 当前 PR 头提交：`3d4e5d8af635705e33599f02bc7dc648d250568d`
- PR #8-#17 均不得在生产恢复前合并
- GroupGuard 不得开始 `GG-CLIENT-001`

## 恢复后再做的发布工具重构

生产恢复完成后，下一版部署流程应改为：

1. 使用临时 `git worktree` 检出目标提交；
2. 以目标 worktree 为 cwd 运行完整测试；
3. 预生成并验证 build-info；
4. 所有预检通过后才创建生产备份和停止服务；
5. checkout 目标提交；
6. 恢复本机配置和持久化状态；
7. 启动并验收；
8. 回滚目标必须同时记录源码提交、build-info、服务配置与启动日志；
9. 回滚后若 `/livez` 不通，自动收集日志并提供直接启动兜底，不得只依赖 Windows 服务状态。

## 新聊天开场指令

用户可直接发送：

```text
继续 LAPI-DEPLOY-001 生产恢复任务。按仓库 docs/CHAT_CHECKPOINT_LAPI_DEPLOY_001_20260729.md、docs/EXECUTION_CHECKPOINT_LAPI_DEPLOY_001_20260729.json 和 docs/NEXT_CHAT_HANDOFF.md 继续。我会上传 recovery diagnostics v2 的完整窗口输出和 diagnostics ZIP。先恢复 5001，禁止继续部署。
```
