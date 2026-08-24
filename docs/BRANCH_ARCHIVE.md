<!-- branch-cleanup-lolapisevers-2026-08-21 -->

# Branch Archive

## 2026-08-21 branch review and cleanup

This document records the reviewed non-default branches before cleanup. The cleanup policy is conservative: delete only branches whose purpose and final outcome are understood; keep any branch that is still tied to the active production baseline or otherwise needs protection. Deleting a branch ref does not delete commits already reachable from `master`.

### Protected production baseline

#### `fix/nssm-appexit-subparameter`
- Reviewed tip: `438d2c2c2400de623a43e9a58436d46fc7037e4d`
- PR: #74, merged into `master` as `28c182c237681b6cbe3d3433ed91af2239385f35`
- Purpose: fix NSSM `AppExit` reads/restores by using the required `Default` subparameter, with a regression test for Windows PowerShell 5.1 persistence updates.
- Current disposition: **KEEP-PRODUCTION-BASELINE**.
- Reason: the live `D:\project2\lolapisevers` working copy is currently detached at this exact branch tip and is used by the running `LOLDataSystem` service. The code is merged, but the remote branch is retained until production is deliberately realigned to a current `master` baseline and verified.

### Reviewed branches approved for deletion

#### `fix/deploy-lineage-master-artifacts`
- Reviewed tip: `5a35de896745dfe5bf869284712aee7bb87a901e`
- Purpose: reconcile production/deployment lineage with the canonical `master` history before later persistence fixes.
- Outcome: **DELETE-ABSORBED**. The tip is reachable from `master`; later deployment/persistence work is based on the reconciled lineage.

#### `fix/winps51-retired-list-array-binder`
- Reviewed tip: `2826fe52e2818c3c403a02d0c93f8d0ebeb5b0dc`
- Related merge: PR #75 / merge `b7359e3b7800abf3f58d5f8413cc850de6d8fa34`.
- Purpose: avoid the Windows PowerShell 5.1 `List[object]` array-binder failure after retiring legacy Startup entries, and add regression coverage.
- Outcome: **DELETE-ABSORBED**.

#### `fix/so1-readiness-auto-recovery`
- Reviewed tip: `6d74d9b34f8396d9d689757bfb560c1073f24d5b`
- Purpose: make SO1 readiness recover stale/corrupt/missing session storage safely, with health/runbook/tests.
- Outcome: **DELETE-ABSORBED**. The branch tip is reachable from `master` and is part of the accepted production lineage.

#### `revert/pr68-target-file-fallback-20260817-final`
- Reviewed tip: `bf15155c614ce22f3fe3f92124cb206b40375042`
- Purpose: final rollback of the PR #68 target-file fallback change after the fix was judged unsafe/incorrect for production behavior.
- Outcome: **DELETE-ABSORBED**. The revert is in `master` history.

#### `fix/target-file-folder-fallback-20260816`
- Reviewed tip: `87fd74989cd91e766e5f92ec1308bf4671f1db44`
- Purpose: target-file folder fallback and single-file provider rotation handling around Lanzou/WER behavior, with endpoint and directory tests.
- Outcome: **DELETE-ABSORBED**. Its accepted history, including later revert decisions, is already represented in `master`.

#### `revert/pr68-target-file-fallback-20260817`
- Reviewed tip: `423066aa7f1251cc96af099adb4048aa40c0824f`
- Purpose: intermediate rollback/reference branch for the PR #68 target-file fallback episode.
- Outcome: **DELETE-ABSORBED**.

#### `revert/pr68-target-file-fallback-20260817-2`
- Reviewed tip: `423066aa7f1251cc96af099adb4048aa40c0824f`
- Purpose: duplicate/intermediate rollback reference for the same PR #68 history.
- Outcome: **DELETE-ABSORBED-DUPLICATE**.

#### `codex/aram-base-live-parser-0811`
- Reviewed tip: `542188a55bdfabe45a2f0fd49f6da41daf085a0a`
- Related merge: PR #67 / merge `634c719075b93fd7d838857195e34453e6bd117c`.
- Purpose: harden the live OP.GG base ARAM balance parser and document parser pitfalls.
- Outcome: **DELETE-ABSORBED**.

#### `codex/aram-full-balance-0811-v2`
- Reviewed tip: `da40c4b3efd0dceee8d5cf8aa52f3caceb271a5e`
- Related merge: PR #66 / merge `656cb4e7d41f8a1eacb2d86bbc0c1bc781491cc6`.
- Purpose: add the complete ordinary-ARAM base balance layer on top of the Mayhem layer, keep the two scopes separate, and integrate the result into sea-rune images and GroupGuard delivery without changing the GroupGuard protocol.
- Outcome: **DELETE-ABSORBED**.

#### `production/current-20260808`
- Reviewed tip: `70a38f1634c9cd07ee95c41b8fb5d35f1531af1c`
- Purpose: preserve the then-current deployed production lineage, including target-file/Lanzou endpoint hotfixes and the 6178 operations path.
- Outcome: **DELETE-ABSORBED**. This production snapshot is an ancestor of current `master`; it is retained here as historical context rather than as a permanent branch.

#### `fix/runtime-startup-topology`
- Reviewed tip: `76cf2921d5e1c835ef43139cda32b40937507e99`
- PR: #72, merged into `master` as `0b3796e8bdce7682ed8c67565fb48d5311380bce`.
- Purpose: retire the legacy Windows Startup chain, enforce a single `LOLDataSystem` service-owned runtime entrypoint, add duplicate-supervisor diagnostics, rollback-safe migration, health checks and tests.
- Outcome: **DELETE-ABSORBED**. The branch looks divergent by raw commit SHA because of merge topology, but the PR itself is merged and is the accepted implementation.

#### `feat/aram-balance-overlay-20260811`
- Reviewed tip: `30cc9e352a1019deff6f0bfe710c6e1e9491b356`
- PR: #64, merged into `master` as `6a7f11f32f086e836b23e0c81e7af13b9b009a9d`.
- Purpose: add optional ARAM Mayhem champion Buff/Debuff data to sea-rune images, with current-patch validation, stale-value suppression, snapshots/cache, renderer overlay and GroupGuard image-path integration.
- Outcome: **DELETE-ABSORBED**. Raw patch ancestry differs from `master`, but the reviewed PR is merged and is the accepted implementation.

#### `codex/aram-full-balance-0811`
- Reviewed tip: `93310b80e058e94c106821c0bbe23f5320bda940`
- PR: #65, closed without merge.
- Purpose: first attempt at complete ARAM balance integration.
- Outcome: **DELETE-OBSOLETE-SUPERSEDED**. PR #65 explicitly states that it was replaced by PR #66 after `master` changed and the old branch carried a non-target deletion risk. The v2 branch was rebuilt from current `master` and merged as the accepted implementation.

## Cleanup rules after this review

- `master` remains the default branch.
- `fix/nssm-appexit-subparameter` must remain until the active production checkout is intentionally moved to a verified current `master` baseline.
- The 13 branches above are approved for remote-ref deletion only if their current tips still exactly match the reviewed SHAs and no new open PR points to them.
- Any SHA drift, new PR, local worktree use, or production dependency is a hard stop and requires re-review.
