# Phase 2 code hygiene and de-template refactor

Date: 2026-09-15

PR: #111 (`refactor/full-code-hygiene-20260914`)

Base: `master@7830d5621986da8b1941e62673defc7d3401f38e`

## Purpose

Phase 2 turns the Phase 1 correctness baseline into clearer runtime ownership and maintainable module boundaries. “De-AI” in this repository means removing patch-shaped architecture: mutable module reloads, import-time side effects, duplicated transports, God modules, and backend files that embed complete browser applications. It does not mean mass-renaming symbols, deleting useful comments, or applying repository-wide formatting for cosmetic reasons.

## Completed changes

### LOLBan runtime ownership

- Added an explicit `LolBanRuntime` registry that owns the active `LolBanService`.
- Replaced `importlib.reload` and mutable router timestamps with atomic service replacement.
- Failed hot reload restores the previous environment and leaves the previous working service active.
- Formal LOLBan queries, GroupGuard queries, health, observability, provider tests and 6178 runtime diagnostics read the same runtime service.

### Application lifecycle

- Application construction no longer initializes persistent runtime resources merely because modules are imported.
- App context creation/startup is owned by FastAPI lifespan.
- Contact-risk SQLite stores expose idempotent `start()` initialization and still lazily self-initialize for direct callers.
- Target-file-watch construction is factory/lifespan owned instead of a module import singleton.

### Provider HTTP transport

- Ordinary configurable Provider requests share `ProviderHttpTransport` for bounded streaming reads, response closure, split connect/read timeouts and explicit redirect behavior.
- Parser Center preserves GET/query, form, JSON and multipart requests, including generated multipart boundaries and empty text fields.
- Dynamic-query private-provider requests reuse the ordinary transport.
- Dynamic-query public providers deliberately keep the DNS-validation / validated-IP pinned `urllib3` transport with original Host/TLS hostname validation. This is a security boundary, not duplication to remove.

### Lanzou monitor decomposition

- `monitor.py` keeps service orchestration, scan state machine, guard/rebaseline logic, event construction and callback delivery.
- `monitor_state.py` owns persisted state/schema behavior.
- `monitor_diff.py` owns snapshot comparison.
- `monitor_errors.py` owns safe error classification/persisted-error sanitization.
- Compatibility exports remain available from `monitor.py`.
- Structural tests prevent StateStore and snapshot-diff implementations from drifting back into the God module.

### 6178 LOLBan UI boundary

- Removed the full inline HTML/CSS/JavaScript application from `lolban_console.py`.
- `control_ui/lolban.py` owns the page shell.
- `control_ui/assets/lolban.css` owns page styles.
- `control_ui/assets/lolban.js` owns browser behavior and admin API calls.
- Existing routes, DOM workflow, provider-token controls and masked-secret behavior remain unchanged.
- CI validates the extracted JavaScript with `node --check`.

## Verification gates

The implementation is covered by:

- Linux unit tests
- Windows unit tests
- generated/control WebUI JavaScript validation
- Windows PowerShell parser validation
- Parser Center dedicated CI plus full suite
- dependency audit
- Ruff correctness rules (`E9`, `F63`, `F7`, `F82`)
- V3 immutable target tests, WinPS 5.1 parsing, dependency audit, package safety/hash verification and artifact upload
- targeted structural boundary tests for lifecycle, monitor ownership and LOLBan UI ownership

## Deliberate non-goals

- No repository-wide formatter pass.
- No opportunistic switch to all Ruff `F`/style/complexity/type rules without measuring the resulting repository impact.
- No removal of the dynamic-query pinned public transport.
- No behavioral redesign of the monitor callback seam in this refactor.
- No conversion of every remaining legacy 6178 page in the same PR.
- No production file modification, service restart, deployment, Release publication or automatic merge.

## Final review expectations

Before merge, the PR head must remain a pure descendant of its `master` base, all required workflows must be green on the actual final head, and unresolved review threads must be zero. Any later code change after that checkpoint invalidates the verification claim and requires a fresh final CI/review pass.
