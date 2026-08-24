# PROJECT2 GitHub 分支清理任务交接文档

更新时间：2026-08-21 06:43 +08:00  
任务范围：`D:\project2` 下多个 GitHub 仓库的历史分支审计、逐分支验收、归档与安全清理。  
核心原则：**先审计、再理解分支用途、再人工验收、最后按精确 SHA 删除；生产目录和活动分支优先保护。**

---

# 1. 当前阶段

本任务已经从“只做 Git 分支数量扫描”推进到“历史分支逐个验收 + 已验收分支安全清理”。

已经完成两个仓库的正式清理：

1. `xianyumht-cmd/groupguard-system`
2. `xianyumht-cmd/lolapisevers`

当前暂停点：

- 下一仓库：`xianyumht-cmd/66rpg`
- 66rpg 先做逐分支人工验收，不直接删除。
- 后续顺序建议继续：
  `66rpg -> facm -> website -> gams -> far2`
- FAR2 必须最后处理，因为 `D:\project2\far2-test` 是真实生产目录且存在活动运行、分支偏离和本地未提交状态。

---

# 2. 任务目标与已确定方法

最初目标是“把 GitHub 上大量历史分支清理干净，但不能丢当前生产代码和有价值开发成果”。

经过审计后，方法已经确定为：

1. 不根据分支名、创建时间、数量直接删。
2. 逐分支回答：
   - 当时是做什么的；
   - 实际改了哪些代码；
   - 是否已经进入默认分支；
   - 是否被新的实现/PR替代；
   - 是否仍与生产、本地 worktree、开放 PR 或重要历史绑定。
3. 人工验收结果统一使用：
   - `DELETE-已吸收`
   - `DELETE-已废弃`
   - `KEEP-仍有价值`
   - `MERGE-值得进入主线`
   - `REVIEW-证据不足`
4. 删除前先在默认分支保存历史归档 `docs/BRANCH_ARCHIVE.md`。
5. 真正删除使用：
   - 精确分支名；
   - 精确 SHA；
   - 删除前再次校验；
   - `--atomic`；
   - 对关键场景使用 `--force-with-lease=<exact SHA>`；
   - 删除后再次读取远程 refs 验证。
6. 不在生产工作树里做 checkout/reset/pull/merge/clean。
7. 不把生产工作树中的未提交/未跟踪内容自动提交到 Git。

---

# 3. 初始总审计结果

核心审计文件：

- `BRANCH-REVIEW-V2-20260821-052811.md`
- `BRANCH-REVIEW-V2-20260821-052811.csv`
- 缓存：`D:\project2\.branch-audit-cache`

V2 对 7 个本地有 origin 的唯一远程仓库共审计 266 个云端分支。

初始总体分类：

- `KEEP_DEFAULT`: 7
- `PROTECT_ACTIVE_LOCAL`: 2
- `PROTECT_LOCAL_HEAD`: 1
- `REVIEW_MERGED`: 95
- `REVIEW_PATCH_EQUIVALENT`: 7
- `REVIEW_TREE_IDENTICAL`: 1
- `REVIEW_UNIQUE_PATCHES`: 148
- `REVIEW_UNKNOWN`: 5

另有 `spark-source` 只有 1 个分支，但因为 `D:\project2` 顶层没有对应本地 origin，未进入该 266 分支审计；最初 8 个 GitHub 仓库总数约 267。

完成 GroupGuard (-8) 和 lolapisevers (-13) 清理后，目前 8 个仓库合计约 **246 个远程分支**：

- groupguard-system: 1
- lolapisevers: 2
- 66rpg: 26
- facm: 83
- far2: 64
- gams: 61
- website: 8
- spark-source: 1

后 6 个仓库尚未进入正式删除阶段。

---

# 4. 已完成：groupguard-system

## 4.1 清理前状态

审计时：

- 默认分支：`main`
- 总分支：9
- `main`: 1
- 其余 8 个全部为 `REVIEW_MERGED`
- 本地 `D:\project2\groupguard-system` 当时 `main` 工作树干净。

8 个历史分支：

- `audit/config-maturity-20260819`
- `docs/record-root-reconcile-production-20260809`
- `docs/record-root-reconcile-production-20260809-duplicate`
- `fix/target-file-retention-cleanup-20260809`
- `fix/target-file-root-reconcile-20260809`
- `hotfix/windows-powershell51-encoding-20260820`
- `hotfix/windows-shell-line-endings-20260820`
- `tmp-ignore`

人工验收结论：

- 全部已被 `main` 吸收；
- duplicate/tmp 分支没有继续保留的独立价值；
- 可归档后删除。

## 4.2 归档

已在云端 `main` 写入：

`docs/BRANCH_ARCHIVE.md`

归档提交：

`a1252ed3041d0775427e1b2d8722d593fd604f3e`

提交说明：

`docs: archive merged branch history before cleanup`

## 4.3 删除

最终成功脚本：

`GROUPGUARD-BRANCH-DELETE-V5.cmd`

删除策略：

- 不 clone；
- 不 checkout；
- 先读取 remote main；
- 逐个验证 8 个分支精确 SHA；
- `git push --atomic origin --delete ...`；
- 删除后逐个 `ls-remote` 验证不存在。

结果：

- 8 个远程历史分支全部删除；
- `main` 保留；
- 本地真实工作树未修改。

GitHub 侧再次复核：

当前只剩：

`main`

当前 main：

`a1252ed3041d0775427e1b2d8722d593fd604f3e`

## 4.4 GroupGuard 未完成问题

`main` 中仍存在一个异常的超长 Trae 相关文件名，内容/路径类似：

`...Trae...safe_rm_aliases.ps1... [Trae] Safe Rm alias...`

这个路径会导致 Windows 普通 checkout 报：

`Filename too long`

该问题**没有在分支清理任务中处理**。

原因：

- 与“历史分支清理”不是同一个问题；
- 清分支时不应顺便改动默认分支其他内容；
- 后续应单独审查该文件为什么进入仓库、是否应删除。

在处理这个异常路径之前，**不要再用普通 Windows working-tree clone 作为 GroupGuard 清理/审计基础**。优先 bare/mirror 或 GitHub API。

---

# 5. 已完成：lolapisevers

## 5.1 清理前环境和风险

真实生产目录：

`D:\project2\lolapisevers`

生产相关证据：

- NSSM 服务：`LOLDataSystem`
- 状态：Running
- Start：Auto
- NSSM AppDirectory：
  `D:\project2\lolapisevers`
- 启动：
  `powershell.exe ... D:\project2\lolapisevers\ops\run_service.ps1`
- 运行过/审计到的服务进程包括：
  - `app.py`
  - `lanzou_update_push_api_server`
  - Playwright / Chromium
- 端口：
  - 5001
  - 6178

生产 Git 状态（审计快照）：

- `D:\project2\lolapisevers`
- detached HEAD：
  `438d2c2c2400de623a43e9a58436d46fc7037e4d`
- 未跟踪：
  - `config/dynamic-query-providers.json`
  - 多个 `config/interface-parser-center.json.bak.*`
  - `diagnostics/`

另有：

`D:\project2\lolapisevers-main-clean`

审计时：

- 分支：`master`
- HEAD：
  `1c39bc062970b1858a0e1e66599129840b07b2ed`
- 当时落后云端 master 38 commits。

## 5.2 自动审计分类

清理前 15 个云端分支：

- `KEEP_DEFAULT`: 1
- `PROTECT_LOCAL_HEAD`: 1
- `REVIEW_MERGED`: 10
- `REVIEW_UNIQUE_PATCHES`: 3

关键点：

自动分类中的“unique patch”不等于代码没有进入 master。

进一步结合 PR 历史确认：

- 某些分支通过 squash/重建/PR merge 已进入 master；
- 单看 ancestry / patch-id 会产生假“未合入”判断；
- 必须结合 PR head、merge commit、PR body 和替代关系。

## 5.3 人工验收结论

保留：

### `master`
默认分支。

### `fix/nssm-appexit-subparameter`
保留为生产保护分支。

分支 tip：

`438d2c2c2400de623a43e9a58436d46fc7037e4d`

PR #74 已经 merged，代码逻辑本身已经进入 master，但真实生产目录当前 detached HEAD 正好还是这个 tip。

PR #74 解决：

`nssm get <service> AppExit`

必须带 `Default` 子参数的问题，并增加 Windows PowerShell 5.1 回归测试。

结论：

`KEEP-PRODUCTION-BASELINE`

**在生产基线完成主动对齐 master、服务验证通过之前不要删除此远程分支。**

批准删除的 13 个：

- `fix/deploy-lineage-master-artifacts`
- `fix/winps51-retired-list-array-binder`
- `fix/so1-readiness-auto-recovery`
- `revert/pr68-target-file-fallback-20260817-final`
- `fix/target-file-folder-fallback-20260816`
- `revert/pr68-target-file-fallback-20260817`
- `revert/pr68-target-file-fallback-20260817-2`
- `codex/aram-base-live-parser-0811`
- `codex/aram-full-balance-0811-v2`
- `production/current-20260808`
- `fix/runtime-startup-topology`
- `feat/aram-balance-overlay-20260811`
- `codex/aram-full-balance-0811`

其中：

- `fix/runtime-startup-topology` 实际已通过 PR #72 合并；
- `feat/aram-balance-overlay-20260811` 已通过 PR #64 合并；
- `codex/aram-full-balance-0811` 的 PR #65 明确被 #66 替代，不应把旧分支重新合回去；
- `codex/aram-full-balance-0811-v2` 对应 PR #66，已经正式合入。

## 5.4 归档

云端 master 已写：

`docs/BRANCH_ARCHIVE.md`

归档提交：

`2fc825e0c55c2cc8801f8eb1bb0c9315e462c3cd`

提交说明：

`docs: archive reviewed branch history before cleanup`

归档文档明确写入：

`fix/nssm-appexit-subparameter = KEEP-PRODUCTION-BASELINE`

## 5.5 删除

成功脚本：

`LOLAPISEVERS-BRANCH-DELETE-V1.cmd`

成功报告：

`LOLAPISEVERS-BRANCH-DELETE-V1-20260821-063614.md`

关键保护：

- 生产 HEAD 必须精确等于 `438d2c2...`
- 云端必须正好是预期 15 分支；
- master 必须精确等于归档提交；
- protected branch 必须存在且 SHA 不变；
- 13 个目标分支 SHA 必须全部不变；
- 本地任何同 origin 仓库不能正在 checkout 删除目标；
- 删除目标 tip 不能匹配本地 repo HEAD；
- 删除使用 `--atomic`；
- 每个分支带 `--force-with-lease=refs/heads/<branch>:<expected SHA>`。

结果：

- 13 个分支全部删除；
- 删除前 exact branch set / SHA 验证通过；
- atomic delete 成功；
- 删除后验证通过；
- Exit code 0；
- 没有修改生产文件、服务、进程或本地 Git 工作树。

当前 GitHub 只剩两个分支：

1. `master`
2. `fix/nssm-appexit-subparameter`

当前 master：

`2fc825e0c55c2cc8801f8eb1bb0c9315e462c3cd`

生产保护 branch：

`438d2c2c2400de623a43e9a58436d46fc7037e4d`

---

# 6. 已验证的安全规则

## 6.1 “远程分支存在”不等于“生产状态已保存”

生产可能包含：

- tracked working-tree changes；
- untracked config；
- runtime data；
- build output；
- diagnostics；
- 生产机独有配置。

所以远程 branch 不能自动等价于完整生产备份。

## 6.2 不自动 commit 生产目录

不要把生产 working tree 的所有修改执行：

`git add -A && git commit`

原因：

- 可能混入 runtime/data/build/cache；
- 可能混入本地配置和密钥；
- 可能把不应进入 Git 的生产状态永久写入仓库。

## 6.3 “REVIEW_UNIQUE_PATCHES”不是最终结论

必须继续看：

- PR 是否 merged；
- merge 是否 squash；
- 分支是否被新分支/PR替代；
- 当前 default 是否已经以不同 commit SHA 实现同一功能；
- 最终文件内容是否等价。

lolapisevers 已经证明：
自动 `git cherry` 的 unique 不足以直接决定 KEEP。

## 6.4 删除必须 exact SHA guard

已跑通的删除模式：

1. 读取当前 remote refs；
2. 验证 default SHA；
3. 验证 protected ref；
4. 验证所有目标 branch exact SHA；
5. 再次验证；
6. atomic delete；
7. post-delete remote verification。

后续继续复用这个模式。

---

# 7. 失败方案、失败原因和结论

以下路线已经失败或被证明不可靠，后续不要重复。

## 7.1 最初“分支数量=1”的审计结果是错误的

旧脚本使用类似：

`git branch -a | find /c "*"`

该命令只统计当前分支前的 `*` 标记，不是分支总数。

结果曾误显示每个仓库只有 1 个分支。

结论：

- 不要再用这个命令统计分支；
- 远程分支枚举应使用 bare mirror / `for-each-ref refs/heads` / GitHub connector。

## 7.2 GitHub Branch Deep Audit V1 失败

原因：

PowerShell helper 参数用了 `$Args`。

PowerShell 变量名大小写不敏感，和自动变量 `$args` 冲突，导致 Git 参数丢失，git.exe 被裸调用。

结果：

- V1 报告 0 repo / 0 branch，无效。

修复：

改为明确的 `$GitArgs`，形成 Deep Audit V2。

不要恢复 V1 写法。

## 7.3 Branch Review V1 失败：PowerShell 5.1 编码

临时 `.ps1` 中包含中文，在 Windows PowerShell 5.1 被错误解码，出现：

- 中文乱码；
- 引号/括号被破坏；
- ParserError。

修复：

Branch Review V2 的 PowerShell source 改为 ASCII-only，中文只放输出数据/外部内容。

不要再次把无 BOM 的中文 PowerShell 源码直接交给 PS5.1。

## 7.4 GroupGuard Cleanup V1：本机 GitHub REST PR 检查失败

脚本通过：

`Invoke-RestMethod https://api.github.com/...`

检查 Open PR。

本机返回错误，清理安全停止。

后续多次出现：

- 404
- 504

结论：

**Windows 本机 PowerShell 对 GitHub public REST 的结果不稳定，不能作为唯一 PR safety gate。**

正确做法：

- 优先通过 ChatGPT GitHub connector 复核 Open PR；
- 本地 REST 可作为附加检查，但失败不等于“有 PR”或“没有 PR”。

## 7.5 GroupGuard Cleanup V2：NativeCommandError

执行：

`git clone ...`

Git 正常把：

`Cloning into ...`

写到 stderr。

Windows PowerShell 5.1 + `$ErrorActionPreference='Stop'` 把 native stderr 转成 `NativeCommandError`，导致脚本提前停止。

修复：

调用 native Git 时临时使用 `ErrorActionPreference=Continue`，最终只认 `$LASTEXITCODE`。

以后所有 PS5.1 Git wrapper 继续使用这种方式。

## 7.6 GroupGuard Cleanup V3：Windows checkout Filename too long

普通 clone 对象下载成功，但 checkout 失败。

根因：

GroupGuard `main` 真的存在一个异常超长 Trae 相关路径/文件名。

错误：

`fatal: unable to checkout working tree`

`Filename too long`

结论：

- 普通 clone/checkout 路线对该仓库不可靠；
- 不要为了“清分支”去修改这个异常路径；
- 使用 bare mirror 或不 checkout 的 Git 操作；
- 异常文件单独立项。

## 7.7 GroupGuard Cleanup V4：TLS handshake

bare mirror clone 失败：

`schannel: failed to receive handshake`

`SSL/TLS connection failed`

这是 Windows 到 GitHub 的临时 HTTPS/TLS 链路问题，不是 Git history 错误。

后续 V5 改为：

- 不 clone；
- 直接 remote `ls-remote`；
- HTTPS 重试；
- HTTP/1.1；
- OpenSSL fallback；
- 可用时 SSH fallback。

最终默认 HTTPS 恢复并成功。

## 7.8 不要反复 clone 大仓库只为删除 refs

GroupGuard 证明：

如果归档已经写入 default，删除历史 refs 根本不需要 checkout/clone working tree。

后续优先：

`ls-remote -> exact SHA gates -> atomic push delete -> ls-remote verify`

只有需要深入 diff/测试时才用隔离 mirror。

---

# 8. 不要重复的路线 / 硬禁止

1. **不要移动、重命名或清理 `D:\project2\far2-test`。**
   它不是测试目录，是 FAR2 真实生产目录。

2. **不要对 `D:\project2\far2-test` 执行：**
   - checkout
   - switch
   - reset
   - clean
   - pull
   - rebase
   - 自动 merge
   - 自动 commit

3. **不要对 `D:\project2\lolapisevers` 为了清分支去切 master。**
   它当前是 LOLDataSystem 真实生产基线。

4. **不要删除 `fix/nssm-appexit-subparameter`。**
   在生产显式对齐 master 并验证前，继续保护。

5. **不要把 branch age / branch name 当删除依据。**

6. **不要把“merged”仅理解为 ancestry；也不要把“unique patch”直接理解为必须保留。**
   要结合 PR/squash/替代关系。

7. **不要 wildcard 删除远程分支。**
   每次只允许人工批准的 exact branch names。

8. **不要在 live repo fetch 只是为了审计。**
   优先临时 mirror / GitHub connector。

9. **不要把 Open PR API 失败当作“没有 Open PR”。**

10. **不要扫入 GAMS 未跟踪文件。**
    已知存在：
    - `SECRET do not push.txt`
    - `gams-signing-key-official.zip`
    - 多个 runtime/browser/test artifact
    这些不能自动 commit。

11. **不要误动 FACM `local-signing/`。**

12. **不要用普通 Windows clone/checkout GroupGuard 作为默认操作路径，直到超长 Trae 文件问题单独解决。**

13. **不要直接同步本地 default 分支到云端 default 来“顺手更新”。**
    例如 lolapisevers-main-clean、far2-main-sync 都可能明显落后云端。

---

# 9. 当前本地代码/提交与环境快照

注意：以下本地状态主要来自 2026-08-21 04:09~05:28 的只读审计。  
GroupGuard/lolapisevers 的云端 default 因本轮新增 `docs/BRANCH_ARCHIVE.md` 已前进 1 个归档 commit。  
继续下一仓库前建议先运行只读状态探测，不要直接假设本地 refs 已同步。

## 9.1 groupguard-system

本地路径：

`D:\project2\groupguard-system`

清理前本地：

- branch: `main`
- 当时 clean
- 当时 HEAD 比现在云端归档 commit 老。

当前云端：

- 只剩 `main`
- main:
  `a1252ed3041d0775427e1b2d8722d593fd604f3e`

因此本地 main 目前大概率会 behind 归档 commit；这是预期状态，不要为了本次任务强行 pull。

## 9.2 lolapisevers

生产路径：

`D:\project2\lolapisevers`

本地生产 HEAD：

`438d2c2c2400de623a43e9a58436d46fc7037e4d`

状态：

- detached
- 有未跟踪 config/backup/diagnostics
- 正被 LOLDataSystem 服务实际使用。

云端：

- master:
  `2fc825e0c55c2cc8801f8eb1bb0c9315e462c3cd`
- protected production branch:
  `fix/nssm-appexit-subparameter`
  `438d2c2c2400de623a43e9a58436d46fc7037e4d`

`D:\project2\lolapisevers-main-clean`

审计时：

- branch: master
- HEAD:
  `1c39bc062970b1858a0e1e66599129840b07b2ed`
- 已明显落后当前云端 master。

不要拿 main-clean 直接覆盖生产。

## 9.3 66rpg

本地：

`D:\project2\66rpg`

审计时：

- branch: `main`
- HEAD:
  `bc4147f9b28b71704819f08f375a20192b4ff89f`
- message:
  `Merge PR #22: publish polished first chapter and modern UI 062`

本地存在 tracked 修改、删除和 untracked 橙光工程/资源文件。

不要在本轮分支清理中 reset/clean/自动 commit。

云端当前仍为 26 个分支。

自动分类：

- KEEP_DEFAULT: 1
- REVIEW_MERGED: 10
- REVIEW_PATCH_EQUIVALENT: 1
- REVIEW_UNIQUE_PATCHES: 14

尚未开始实际删除。

## 9.4 FACM

本地：

`D:\project2\Facm`

审计时：

- branch: `main`
- HEAD:
  `2e47cc400228d1c6a0d9f6e112e11bb371d1c87d`
- `main...origin/main`
- untracked:
  `local-signing/`

云端 83 分支。

Branch Review V2 分类：

- KEEP_DEFAULT: 1
- REVIEW_MERGED: 47
- REVIEW_PATCH_EQUIVALENT: 3
- REVIEW_TREE_IDENTICAL: 1
- REVIEW_UNIQUE_PATCHES: 29
- REVIEW_UNKNOWN: 2

此前观察到过开放 PR；实际清理前必须重新实时查询，不可使用旧结果。

## 9.5 website

本地：

`D:\project2\website-main`

默认云端分支：

`source`

本地审计时：

- branch: `source`
- HEAD:
  `c27caee878f20ed5a9717b7b6d4e4463831a58c9`
- untracked:
  - `design-previews/`
  - `output/`

云端 8 分支。

Branch Review V2：

- KEEP_DEFAULT: 1
- REVIEW_PATCH_EQUIVALENT: 1
- REVIEW_UNIQUE_PATCHES: 6

`nav-lol-26-16` 是 patch-equivalent 候选，但必须人工确认当前 `source` 是否已经以其他提交实现同一 LOL 版本更新。

## 9.6 GAMS

本地：

`D:\project2\gams`

活动分支：

`codex/fix-all-audited-bugs-20260801`

HEAD：

`f7958d3950e74f6c6277c35fce6780a547278dac`

状态：

- active local
- tracked 修改：
  `remote-script/src/noname.js`
- 大量 untracked
- 含敏感/签名文件：
  - `SECRET do not push.txt`
  - `gams-signing-key-official.zip`

云端 61 分支。

Branch Review V2：

- KEEP_DEFAULT: 1
- PROTECT_ACTIVE_LOCAL: 1
- REVIEW_MERGED: 10
- REVIEW_PATCH_EQUIVALENT: 1
- REVIEW_UNIQUE_PATCHES: 45
- REVIEW_UNKNOWN: 3

该仓库风险高，不能自动归档所有 untracked。

## 9.7 FAR2

真实生产路径：

`D:\project2\far2-test`

不要被目录名误导。

当前生产本地分支：

`feature/qq-seed-batch-evidence-20260814`

本地 HEAD（最新现实状态探测）：

`c792e64e...`

该 HEAD 包含一次：

`Merge branch 'deploy/bug-audit-20260821-022631' into feature/qq-seed-batch-evidence-20260814`

本地生产 working tree 仍有 tracked 修改/删除和大量 untracked runtime/build/data。

云端该 feature branch 审计时 tip：

`fb9ead9acfdc988cd3971ac3fff8125b2d6dbea2`

注意：

**本地生产 HEAD 与云端 branch tip 不是同一个 commit。**

FAR2 云端 64 分支。

Branch Review V2：

- KEEP_DEFAULT: 1
- PROTECT_ACTIVE_LOCAL: 1
- REVIEW_MERGED: 10
- REVIEW_PATCH_EQUIVALENT: 1
- REVIEW_UNIQUE_PATCHES: 51

其它工作树：

- `D:\project2\far2-main-sync`
- `D:\project2\far2-backups\BUG-AUDIT-20260821-022631\integration-worktree`
- `D:\project2\far2-wechat-probe`

这些有注册 worktree/历史用途，不要随意移动或删目录。

FAR2 必须最后清理远程分支。

---

# 10. 66rpg 当前待办（下一步）

当前云端分支数：

26

当前分支名单：

- `agent/bug-audit-058-20260801`
- `agent/fix-all-bugs-059-20260801`
- `agent/m03-character-runtime-056`
- `agent/m03-visual-gate-058`
- `agent/m04-assistant-directed-063`
- `agent/m04-candidates-058-062-transfer`
- `agent/orange-runtime-evidence-060-20260801`
- `agent/orange-runtime-fix-061-20260801`
- `agent/production-ch01-ui-062-20260802`
- `agent/t052-034-character-production-057`
- `art-direction-028-identity-lock`
- `art-direction-029-four-master-lock`
- `ci/ch01-cover-load-repair-051-v2`
- `ci/ch01-cover-load-repair-051`
- `ci/ch01-runtime-contract-050-20260728`
- `ci/ch01-runtime-contract-050-v2`
- `ci/ch01-runtime-contract-050-v3`
- `ci/work-plan-052-validation`
- `custom-name-capture-031`
- `exec/plan-052-m00-m01`
- `exec/plan-052-m02-design`
- `main`
- `noop`
- `product-spec-030-customization-dynamic-cg`
- `work/m02-visual-approval-054`
- `work/m03-character-layout-runtime-055`

自动分类：

- 10 merged
- 1 patch-equivalent
- 14 unique
- main 1

## 66rpg 下一步执行方式

### Step 1：只读复核当前状态

重新确认：

- 26 个分支是否仍未变化；
- main SHA；
- Open PR；
- 本地 main HEAD 和 dirty 状态；
- 目标分支 tip SHA。

不要先删。

### Step 2：先验收 10 个 REVIEW_MERGED

逐个确认：

- 分支用途；
- PR / merge commit；
- 进入 main 的功能；
- 是否只是阶段 checkpoint / CI repair / production candidate。

优先标记：

`DELETE-已吸收`

但仍要人工看语义，不因为 `REVIEW_MERGED` 四个字直接全删。

### Step 3：验收 1 个 REVIEW_PATCH_EQUIVALENT

确认它是否：

- squash/rebase/cherry-pick 进入 main；
- 或最终 tree 仍有语义差异。

如果功能已经等价：

`DELETE-已吸收`

### Step 4：逐个审 14 个 REVIEW_UNIQUE_PATCHES

重点判断它们属于：

- 旧计划阶段；
- 已被新里程碑替代；
- 失败/实验分支；
- 仍有尚未进入 main 的正式剧情/资源/脚本能力。

不要因为当前作品“可用/稳定”就直接丢掉 unique code。

### Step 5：生成 66rpg 人工验收结论

每分支必须得到一个最终状态：

- DELETE-已吸收
- DELETE-已废弃
- KEEP-仍有价值
- MERGE-值得进入主线
- REVIEW-证据不足

### Step 6：写 `docs/BRANCH_ARCHIVE.md`

只记录已经完成语义验收的分支：

- branch
- tip SHA
- PR
- 开发目的
- 主要完成
- 最终去向
- 被哪个 main commit/新分支替代
- 删除原因

### Step 7：只删除批准 refs

复用 lolapisevers 成功模式：

- 精确 main SHA；
- 精确 target SHA；
- Open PR 再检查；
- local branch / local HEAD 保护；
- `--atomic`
- `--force-with-lease`
- post-delete 验证。

---

# 11. 后续仓库顺序

建议继续：

## 1. 66rpg
现在开始。

## 2. FACM
分支最多之一，但已有 47 个 merged 候选。
注意 open PR 和 `local-signing/`。

## 3. website
分支少，但几乎没有 ancestry-merged，需要语义判断。
不要机械删。

## 4. GAMS
高风险。
活动本地分支 + 未提交 JS + 密钥/签名文件。
必须单独保护。

## 5. FAR2
最后处理。
因为：

- 真实生产目录；
- 活动服务；
- dirty working tree；
- 本地生产 HEAD 已超出云端 branch tip；
- 多个 worktree；
- 历史开放 PR；
- 生产状态不能仅靠 Git remote 还原。

---

# 12. 本轮使用/生成的重要脚本和报告

## 审计

- `PROJECT2-REALITY-SCAN-V3.cmd`
- `D:\project2\PROJECT2-REALITY-MAP-V3.txt`
- `GITHUB-BRANCH-DEEP-AUDIT-V2.cmd`
- `GITHUB-BRANCH-DEEP-AUDIT-V2-*.md/csv`
- `BRANCH-REVIEW-V2.cmd`
- `D:\project2\BRANCH-REVIEW-V2-20260821-052811.md`
- `D:\project2\BRANCH-REVIEW-V2-20260821-052811.csv`

## GroupGuard

失败/中间版本：

- `GROUPGUARD-CLEANUP-PHASE1.cmd`
- `GROUPGUARD-CLEANUP-PHASE1-V2.cmd`
- `GROUPGUARD-CLEANUP-PHASE1-V3.cmd`
- `GROUPGUARD-CLEANUP-PHASE1-V4.cmd`

最终成功：

- `GROUPGUARD-BRANCH-DELETE-V5.cmd`
- `D:\project2\GROUPGUARD-BRANCH-DELETE-V5-*.md`

## lolapisevers

最终成功：

- `LOLAPISEVERS-BRANCH-DELETE-V1.cmd`
- `D:\project2\LOLAPISEVERS-BRANCH-DELETE-V1-20260821-063614.md`

---

# 13. 当前已完成成果汇总

## groupguard-system

已完成：

- 8 个历史分支人工验收；
- 归档到 main；
- 8 个远程分支删除；
- 删除后 GitHub 复核；
- 当前只剩 main。

## lolapisevers

已完成：

- 14 个非默认分支人工语义复核；
- 13 个批准删除；
- 1 个生产保护；
- 归档到 master；
- 13 个远程分支 atomic + lease 删除；
- 删除后 GitHub 复核；
- 当前只剩 master + 生产保护 branch。

总计已经删除：

**21 个远程历史分支**

且：

- 没有修改 FAR2 生产；
- 没有修改 LOLDataSystem 生产工作树；
- 没有重启生产服务；
- 没有 reset/clean；
- 没有把未跟踪生产数据自动提交。

---

# 14. 当前未完成问题

1. 66rpg 26 个分支尚未人工验收完。
2. FACM 83 个分支尚未清理。
3. website 8 个分支尚未清理。
4. GAMS 61 个分支尚未清理。
5. FAR2 64 个分支尚未清理。
6. spark-source 只有 1 个分支，暂不需要清理。
7. GroupGuard main 的异常超长 Trae 文件尚未处理。
8. lolapisevers 生产仍未从 `438d2c2...` 主动对齐最新 master。
9. `fix/nssm-appexit-subparameter` 仍需保留，不能删除。
10. 各仓库本地 default refs 不一定同步云端归档 commit；不要为了“看起来一致”直接 pull live repo。
11. `.branch-cleanup-work` 下可能存在前面失败 clone 留下的临时目录，尚未作为本任务重点清理；不要把这些临时目录当正式工作树。需要清理时先确认它们不是 registered worktree/生产引用。

---

# 15. 下一聊天/下一操作者直接执行提示

从这里继续，不要重跑已成功的 GroupGuard/lolapisevers 删除。

直接进入：

`xianyumht-cmd/66rpg`

第一目标：

**逐个审查 66rpg 的 25 个非 main 分支，先处理 10 个 REVIEW_MERGED，再处理 1 个 PATCH_EQUIVALENT，最后分析 14 个 UNIQUE_PATCHES。**

不要先生成删除脚本。

先基于：

- `BRANCH-REVIEW-V2-20260821-052811.md`
- GitHub 当前 branch refs
- PR 历史
- commit/diff
- 当前 main

为每个分支给出人工结论。

只有用户确认该批结论后：

1. 写 `docs/BRANCH_ARCHIVE.md`
2. 记录归档 commit SHA
3. 创建 exact-SHA guarded deletion CMD
4. `--atomic + --force-with-lease`
5. 删除后通过 GitHub connector 再复核。

---

# 16. 一句话暂停点

**GroupGuard 已清为仅 main；lolapisevers 已清为 master + 生产保护分支；下一步从 66rpg 的 25 个历史分支开始逐个验收，暂时不要删除。**
