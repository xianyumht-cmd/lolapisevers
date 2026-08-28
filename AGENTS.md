# AGENTS.md — Mandatory AI Repository Rules

> **ChatGPT / Codex / other coding agents: read this file before any repository action.**
> These are standing user instructions. Do not wait for the user to repeat them in a new chat.

## 1. Canonical state

- Canonical development branch: `master`.
- Production pointer: `production/current-20260808`.
- Normal development must start from the latest `master`.
- `production/*`, accepted production tags, and `archive/*` tags are historical/production references, not development bases unless the user explicitly says otherwise.
- Do not infer production truth from a branch name alone; verify the exact commit/runtime evidence when production is involved.

## 2. Local production separation

- Production working tree: `D:\project2\lolapisevers` — **READ ONLY during normal development**.
- Canonical development working tree: `D:\project2\lolapisevers-main-clean`.
- Do not fetch, merge, checkout/switch, reset, clean, stash, rebase, or edit the production working tree during ordinary development.
- Do not restart or deploy the production service unless the user explicitly authorizes a production deployment in the current task.

## 3. One task = one temporary branch

- Before creating a branch, check whether the same task already has an active branch or PR. Reuse it if it is genuinely the same task.
- Otherwise create exactly one short-lived branch from the latest `master`.
- Continue fixes/revisions on that same task branch. Do **not** create `v2`, `v3`, `final`, `current`, `backup`, `test`, `build`, `deploy`, `handoff`, `note`, or similar auxiliary branches.
- Do not use branches as chat memory, backups, build containers, deployment packages, or status markers.
- Unfinished work belongs in a GitHub Issue or repository task-state document.

## 4. Builds, releases, and history

- Use GitHub Actions artifacts for build/deployment packages.
- Use immutable tags for accepted candidates, production versions, and historical snapshots.
- If unique old history must be retired, create and verify an `archive/*` tag before deleting its branch.
- Never delete unique history merely because a branch looks old or temporary.

## 5. Task completion

A development task is complete only when:

1. implementation is finished;
2. tests/CI pass;
3. the PR is merged;
4. `master` is verified to contain the result;
5. the temporary task branch is deleted;
6. the related Issue/task-state record is updated.

Do not leave merged/closed task branches behind by default.

## 6. Git safety — hard rules

Do not use unless the user explicitly authorizes a narrowly defined recovery operation:

- force push;
- `git reset --hard`;
- history-rewriting rebase;
- `git clean`;
- `git stash`;
- destructive branch/ref moves;
- automatic branch switching as an error-recovery shortcut.

If the worktree is dirty, the origin is unexpected, the branch is not what you expect, history has diverged, or a safe fast-forward/merge path is unclear: **stop and report the exact state instead of rewriting history**.

Never commit secrets, tokens, runtime credentials, local environment files, diagnostic dumps containing credentials, or unrelated generated files.

## 7. AI takeover protocol

At the start of every task:

1. read this `AGENTS.md` and any more specific nested `AGENTS.md`;
2. identify the current branch, default/canonical branch, origin, and working-tree status;
3. inspect the relevant Issue/PR when the task references one;
4. distinguish development state from production/runtime state;
5. make the smallest safe change on one task branch.

For read-only diagnosis, do not create a branch just to investigate.

For destructive Git operations, production deployment, service restart, branch deletion, tag deletion, or history rewriting, require explicit user intent and perform fresh safety checks immediately before the action.

## 8. Long-term branch budget

The healthy persistent remote branch set for this repository is intentionally small: normally `master` plus the current production pointer. Temporary feature/fix branches should exist only while their task is active.

## 9. Self-maintaining AI knowledge system

The user should **not** need to remember or repeat project-history and documentation chores. When the user has authorized a repository-changing task, maintaining the repository knowledge files below is part of that task and does not require a separate reminder. Do not perform repository writes during a purely read-only request.

### Knowledge takeover order

After reading all applicable `AGENTS.md`, read the following canonical knowledge files when they exist, then verify important claims against current Git/Issue/PR/runtime evidence:

1. `docs/AI_CONTEXT.md` — stable project purpose, boundaries, major modules, external dependencies, and terminology.
2. `docs/PROJECT_STATE.md` — current verified development/production state, active Issues/PRs, accepted versions, incomplete work, and next actions.
3. `docs/PITFALLS.md` — recurring mistakes, failed approaches, root causes, detection signals, and prevention rules.
4. `docs/DECISIONS.md` — durable technical/product/operations decisions and why they were made.
5. `docs/ARCHITECTURE.md` — components, ownership boundaries, data flow, contracts, and important integration relationships.
6. `docs/OPERATIONS.md` — build, release, deployment, verification, recovery, rollback, and maintenance runbooks.
7. `docs/AI_WORKSTYLE.md` — stable repository-relevant collaboration preferences that help AI work effectively with the user.

Missing files are not an error. **Do not create empty boilerplate files.** Create a canonical file only when the first real piece of durable information belongs there.

### Automatic routing rules

- Put only durable mandatory AI behavior, safety constraints, and repository workflow rules in `AGENTS.md`.
- Put stable project facts and vocabulary in `AI_CONTEXT.md`.
- Put time-sensitive current state in `PROJECT_STATE.md`; keep it concise and remove/replace stale state instead of endlessly appending chat-style logs.
- When an AI mistake, failed approach, or user correction could reasonably recur, record the lesson in `PITFALLS.md` with cause + prevention, not just the symptom.
- When a durable choice is made between alternatives, record it in `DECISIONS.md` with date, decision, reason, consequences, and superseded decision when applicable.
- When component boundaries, protocols, dependencies, or data flow materially change, update `ARCHITECTURE.md`.
- When build/deploy/rollback/verification procedures materially change, update `OPERATIONS.md`.
- Put stable collaboration preferences in `AI_WORKSTYLE.md` only when they are relevant to repository work; do not store unrelated personal profile information.
- Do not create `*-v2.md`, `final-notes.md`, dated handoff duplicates, or parallel knowledge files when a canonical file can be updated.
- Do not create a separate branch merely to write task handoff/knowledge updates; include them in the same authorized task branch/PR.

### Automatic maintenance triggers

During every substantive task, the agent must decide whether the work created knowledge worth preserving. Before declaring the task complete:

1. reconcile documentation claims with the actual current Git/Issue/PR state and, when relevant, verified runtime evidence;
2. update `PROJECT_STATE.md` if canonical branch, production state, accepted version, active task, blocker, or next action materially changed;
3. update `PITFALLS.md` if a meaningful failure or correction produced a reusable prevention lesson;
4. update `DECISIONS.md` if a durable decision was made;
5. update `ARCHITECTURE.md` or `OPERATIONS.md` when their facts changed;
6. update `AI_CONTEXT.md` / `AI_WORKSTYLE.md` only for stable facts/preferences, not temporary conversation details;
7. update `AGENTS.md` itself only when a new long-lived mandatory rule is discovered.

A task is **not fully closed** if repository knowledge is materially stale after the change.

### Evidence and hygiene rules

- Repository/runtime evidence is the source of truth; stale documentation must not override fresh evidence.
- Clearly distinguish **verified current state**, **planned work**, and **inference**.
- Prefer exact Issue/PR numbers, tags, commit SHAs, paths, service names, and dates when they make a record auditable.
- Never store passwords, API tokens, cookies, private keys, session secrets, or credential-bearing diagnostics in these knowledge files.
- Do not copy large logs or chat transcripts into the knowledge base; summarize the reusable conclusion and point to durable evidence when available.
- If existing knowledge conflicts with reality, correct or mark it superseded as part of the current task instead of silently working around it.

The goal is that a future ChatGPT/Codex session can enter the repository, read the canonical files, inspect live repository state, and continue safely **without relying on the user to remember previous instructions or retell project history**.

## 10. Runtime / WebUI configuration parity

Treat configuration behavior as one cross-surface contract. Runtime logic and the control plane must never knowingly implement different meanings for the same setting.

- Any change to a configuration key, default, allowed value, normalization rule, inheritance rule, precedence rule, feature switch, output mode, or other runtime behavior controlled by configuration must inspect and update **all affected surfaces in the same task/PR**: runtime resolution, WebUI display/effective preview, WebUI edit/save mapping, admin/query APIs, migrations/defaults, documentation, and tests.
- A plugin/runtime change is not complete if the WebUI still displays, edits, saves, or explains the old behavior. A WebUI change is not complete if the runtime/API still interprets the setting differently.
- WebUI pages that claim to show a final/effective value should prefer a server-side canonical resolved value and its source. If the browser must derive the value, its precedence must be identical to runtime and protected by parity tests.
- For changed configurable behavior, regression coverage must include the relevant precedence layers, including where applicable: global default, feature/profile value, explicit group override, and inherited/no-override group. Tests must assert that runtime delivery and WebUI/API effective preview agree.
- Distinguish an **explicit group override** from a value merely present in an already-resolved/effective group object. An inherited global value must not accidentally masquerade as a group override and mask a more specific feature/profile setting.
- When a bug is caused by runtime/WebUI drift, fix the shared contract and add a regression that would have caught the divergence; do not patch only the visible label or only the runtime branch.
- Before merging, explicitly verify every affected configuration surface. If a surface is intentionally unaffected, record why in the PR/test evidence rather than assuming it is synchronized.