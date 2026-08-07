# 定向文件推送接口端修复进度 — 2026-08-08

本文件续接 `HANDOFF_TARGET_FILE_PUSH_20260808.md`，原交接中的生产约束继续生效。

## 已完成的接口端修复

### 1. 目录枚举与单文件直链解析拆分

`services/target_file_watch_directory.py` 已拆为目标文件推送自己的两层职责：

- `TargetFileDirectoryResolver`：只负责目录枚举、稳定 key / fingerprint 和 Provider 切换保护。
- `TargetFileDirectResolver`：只接收一个已经确定的具体文件 `share_link`，再调用 WER 单文件解析能力取得 fresh `direct_url`。

`resolve_for_delivery()` 现在执行：

```text
source folder URL
-> refresh directory snapshot
-> match target key + canonical fingerprint
-> metadata.share_link
-> TargetFileDirectResolver.resolve(metadata.share_link)
-> fresh direct_url
-> callback 6108
```

不再执行：

```text
source folder URL
-> WER
-> 从 WER 目录结果再次匹配目标文件
```

### 2. 配置边界已独立

新增 `TargetFileWatchProviderConfig` 与 `load_target_file_watch_provider_config()`。

- 定向文件推送不再直接依赖旧蓝奏监控的完整 `AppConfig` / `ProviderChain` 业务顺序。
- 第三方 WER Secret 默认继续复用现有 `LANZOU_API_KEY`，无需生产维护第二份相同 Secret。
- 可选的目标功能专属环境变量：`TARGET_FILE_WATCH_WER_ENDPOINT`、`TARGET_FILE_WATCH_WER_KEY` 等。
- 日志只记录 Provider/异常类型，不输出真实 Secret 或异常原文中的敏感值。

### 3. fail-safe 语义保持不变

以下规则没有放宽：

- callback 成功前不推进 baseline；
- direct resolver 失败时 pending 保留；
- 删除-only 不调用 direct resolver；
- 空快照不覆盖正常非空 baseline；
- Provider 切换不制造批量误上传；
- 投递前重新读取目录并验证目标文件 fingerprint，旧事件失效时拒绝投递。

## 新增回归覆盖

`tests/test_target_file_watch_directory.py` 已覆盖：

1. 新增文件使用自己的 `share_link`，不是目录 `source_url`；
2. 同名替换使用新版本最新 `share_link`；
3. 多新增文件逐个使用各自 `share_link`；
4. 删除-only 不调用 direct resolver；
5. direct resolver 失败时 callback 不执行、baseline 不前移、pending 保留；
6. source folder URL 不能作为 direct URL；
7. 定向文件目录 Provider 策略不受旧蓝奏 Provider 顺序控制；
8. WER 单文件解析收到的是具体文件分享链接；
9. Provider 异常与错误提示不泄漏 Secret。

## 已验证结果

在接口修复 head `4fd3a7c374c430316c753841933afdc3da6d3a84`：

- Linux compile + full unit tests：通过；
- Windows compile + full unit tests：通过；
- LAPI Parser Center CI：通过；
- `tests` 总工作流仅被独立 dependency-audit 阻塞。

dependency-audit 当前报告：

```text
cryptography 49.0.0  PYSEC-2026-3552  Fix Versions: 50.0.0
```

截至 2026-08-08，官方 PyPI 最新公开版本仍为 `cryptography 49.0.0`，因此不能把 `requirements.txt` 锁到尚未发布的 50.0.0 来制造假通过。曾做的 50.0.0 临时尝试已撤回。

## V3 安全部署工作流修正

发现 `.github/workflows/build-production-safe-deployment-v3.yml` 原先把目标提交固定为旧 SHA `4a29a0a...`，导致 PR 更新后仍在打旧代码。

现已改为：

```yaml
TARGET_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}
```

因此 PR 场景应打包当前 PR head，push / workflow_dispatch 使用当前 `github.sha`。

目前 GitHub Actions 新 Job 出现“未进入任何步骤即失败（steps=null）”的 Runner/调度异常，连 checkout 都没有开始；这不是业务单测断言失败。不要因此关闭依赖审计或绕过部署安全门。

## 当前分支/提交

接口端分支：`feat/target-file-push-20260807`

关键提交：

- `994daaa220b692e851c670528a2be1db6cc91cb5` — direct URL 改为从目标文件 share_link 解析；
- `4fd3a7c374c430316c753841933afdc3da6d3a84` — 补定向文件 direct resolver 回归测试；
- `de5f71d8748ae530c9bda4564b7ac88d5d339a44` — V3 打包器改为跟随当前 PR head；
- `2627bd853eb097d2b3279213e928aa6e7a02a166` — 撤回不可安装的 cryptography 50.0.0 临时 pin，保持已发布 49.0.0。

## 生产状态必须保持

当前生产仍不要做以下操作：

- 不要重新建立 baseline；
- 不要重部署 GroupGuard 6108；
- 不要重做/重部署 6178 页面；
- 不要清空当前 pending；
- 不要把当前待投递 `U13LKcQg2.7z` 吞进新 baseline。

待安全部署候选生成并验证后，只部署接口端 5001 修复，然后在保留现有 baseline/pending 的前提下执行一次立即检查，最终验证：

```text
5001 检测 pending 文件
-> 使用 U13LKcQg2.7z 自己的 share_link 解析 direct_url
-> callback 6108
-> 6108 下载临时文件
-> 上传 QQ 原生群文件
-> 成功后推进 baseline / 完成 eventId 去重
```

如果任何一步失败，继续保持旧 baseline 与 pending，不能静默 rebaseline。
