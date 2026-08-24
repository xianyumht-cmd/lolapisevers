# Project state

更新时间：2026-08-24 +08:00

## Canonical development

- 默认开发分支：`master`
- 当前任务：Issue #76「海符榜富信息重构与 WebUI Release 一键升级」
- 当前任务分支：`feat/aram-rich-release-updater`
- 生产目录与生产服务未在本任务中直接修改或重启。

## 当前任务范围

- 海符榜：保留原 `rows` API 兼容数据，OP.GG 强化解析补充 `id`、`rank`、可用样本数与清理后的说明文本；图片改为按棱镜/黄金/白银分层的强化决策视图，并明确区分单符数据推导与真实组合胜率。
- 英雄平衡：继续保留基础 ARAM 与 Mayhem 分层平衡修正，不把两个层级的数值相加。
- WebUI：`/system` 增加 GitHub Release 检查、只读 Token 配置和一键升级入口。
- 更新器：只接受固定仓库的 V3 ZIP + metadata；校验文件名、目标提交、SHA-256、V3 revision、metadata 安全标志和嵌入 manifest 安全标志后，才启动独立 PowerShell 部署进程。
- CI：PR 继续生成 V3 候选 Artifact；`master` push 在同一套测试和包校验通过后，由单独的最小写权限 job 发布 GitHub Release。

## 当前安全边界

- Release Token 不回显，不写入源码；默认保存在生产机 `ProgramData/LOLDataSystem/updates`，也可由 `LOLAPI_UPDATE_GITHUB_TOKEN` 环境变量提供。
- 一键升级不会在 6178 进程内直接覆盖自身，下载与校验完成后启动独立 PowerShell 进程。
- V3 部署包继续负责候选测试、生产备份、基线健康检查、切换、后置验证与失败自动回滚。
- CI 会检查 V3 部署脚本是否出现 WebUI 更新器无法解析的新增必填参数。

## 完成条件

1. 新增单元测试、全仓 compileall、UI asset check、JavaScript 检查与 Windows PowerShell 5.1 检查全部通过。
2. V3 候选包成功构建并通过 metadata / manifest / SHA-256 验证。
3. PR 合并到 `master`。
4. `master` 的 V3 Release 成功发布。
5. 首次仍按现有 V3 包部署；从该版本之后可在 6178 `/system` 使用 Release 一键升级。
