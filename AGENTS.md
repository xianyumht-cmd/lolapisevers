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
