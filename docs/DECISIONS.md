# Technical decisions

## 2026-08-31 — Measure the complete query-to-OneBot path before changing transport

**Decision**

Treat API query/render, GroupGuard plan construction, and the send queue as
separate latency boundaries. Keep the current base64 delivery contract while
adding safe stage timing across those boundaries; do not switch to a public
CDN, URL delivery, or local-file delivery based only on a multi-second
aggregate metric.

**Reasons**

- Production is split between 121 (bot/OneBot) and 100 (LOL API), but the
  measured network connection is about 1.4ms.
- Warm battle images return from 100 in about 0.09–0.21s, while cold business
  queries and post-API sends are multi-second in different samples.
- The existing GroupGuard plugin metric is recorded before structured response
  sending, so it cannot identify queue or OneBot time.
- The current OneBot client accepts the tested base64 image representation and
  changing it would expand compatibility and rollback risk without a measured
  benefit.

**Consequences**

- API timing exposes only bounded stage metadata: elapsed milliseconds, cache/
  asset state, dimensions, and byte counts.
- GroupGuard records T0/T1/T2/T3/T4/T8/T9 without storing user content or
  credentials.
- Any future transport optimization must compare cold and warm cases, verify
  OneBot support, and preserve text/image/forward fallback behavior.

## 2026-08-31 — No production deployment during the latency audit

**Decision**

The audit and instrumentation are developed on task branches only. The
production working tree, 121 containers, and 100 service are not restarted,
rewritten, or deployed as part of this task.

**Reason**

The goal is to establish a trustworthy baseline first; an unverified runtime
change would make before/after comparisons ambiguous and increase recovery
risk.

## 2026-08-24 — Production updates use verified GitHub Releases

**Decision**

Future WebUI self-updates use GitHub Releases containing the existing V3 production-safe ZIP and its `.metadata.json`, rather than `git pull`, source-tree overwrite, or temporary GitHub Actions artifacts.

**Reasons**

- Release assets are immutable, auditable deployment inputs tied to a concrete commit.
- The V3 package already contains candidate validation, offline dependencies, production backup, readiness verification and automatic rollback.
- A running 6178 process must not overwrite its own source tree. WebUI only downloads and verifies the release, then starts an external PowerShell deployment process.
- Actions artifacts remain useful for PR candidate testing, but are retention-limited and are not a durable production update channel.

**Consequences**

- Every `master` push is tested and packaged; only after the V3 job succeeds can a separate job with `contents: write` publish the latest Release.
- Private-repository production machines need a GitHub token with only the permissions required to read Releases/contents. The real token is never returned by the WebUI.
- The updater rejects unknown package names, mismatched target commits, invalid SHA-256 values, non-V3 metadata, missing safety flags, path-traversal ZIPs, or embedded manifests that do not match the release target.

## 2026-08-24 — Release download control uses a background worker, not a long-lived request

**Decision**

The 6178 Release updater runs download/verification as a process-local background worker. The start API only accepts the task and returns; WebUI progress/control requests are separate short HTTP calls. Persisted state is not treated as proof that a worker is alive.

Windows service restart verification is likewise based on an observed service PID replacement, not on whether `Restart-Service` was successfully launched or whether the WebUI quickly became reachable again.

**Reasons**

- A long-lived `/admin/update/start` request couples browser/network lifetime to an 80+ MiB download and makes pause/reconnect semantics awkward.
- `update-state.json` survives process restarts, while Python download threads do not. Therefore a persisted `downloading` value can become false evidence after service restart.
- Socket read timeout does not detect a connection that continually trickles data below a useful throughput.
- NSSM can stop and restart the service and both child servers in a few seconds, so browser reachability cannot distinguish “never restarted” from “already restarted”.

**Consequences**

- Active update state includes worker PID, run id and heartbeat. A new process that sees an orphaned active state converts it to `interrupted` and offers breakpoint resume.
- WebUI exposes pause, resume, reconnect and explicit reset-from-zero controls.
- Download progress/control checks use smaller chunks plus a low-speed time window; low-speed reconnect keeps `.part` and never bypasses SHA-256/manifest validation.
- Service restart is only marked `verified` after `Running` is observed with a new non-zero PID; timeout leaves the result `unverified`.

## 2026-08-24 — ARAM recommendations must not invent combination win rates

**Decision**

The sea-rune image may derive practical pick directions from single-augment win rate and popularity, but derived recommendations must be labeled as such and must not be displayed as measured three-augment combination win rates.

**Reasons**

The current OP.GG upstream parser supplies per-augment performance/popularity data. Combining those values mathematically would not create a statistically valid observed combination win rate.

**Consequences**

- The image groups augments by quality and shows single-augment metrics directly.
- “稳健首选 / 高胜上限 / 热门容错” are decision aids derived from single-augment data.
- The rendered image explicitly states that those routes are not measured three-augment combination win rates.

## 2026-08-25 — Release self-update is forward-only and ancestry-gated

**Decision**

The WebUI updater may automatically install a Release only when GitHub can prove that the Release target is a descendant of the currently running production commit. A different SHA is not sufficient evidence of an upgrade.

Idle updater status refreshes the latest Release instead of letting an old failed/interrupted `update-state.json` remain authoritative. Commit relationship is evaluated against GitHub's official Compare API using `current...target`.

**Reasons**

- A production machine can legitimately run a tested PR candidate that is newer than the most recently published Release. In that state, `target != current` would incorrectly treat an older Release as an upgrade and could roll production backward.
- A persisted failed task describes an old attempt, not the current release channel. It must remain diagnostic history rather than determine the newest available target indefinitely.
- Production repositories may not have every future Release commit object locally, so a local-only `git merge-base` check is not reliable enough for the release channel. GitHub already has both commits and can authoritatively compare them.

**Consequences**

- `current...target = ahead` is the only normal automatic forward-update relation.
- `identical` means no update is required.
- `behind` means the Release is older than current production and downgrade is blocked.
- `diverged` or an unavailable/unknown relationship is fail-closed; automatic update is blocked rather than guessed.
- The same guard applies to start, resume, reconnect, and reset paths, not only to the WebUI button state.
- Active download/deployment polling remains local-only; GitHub Release and compare calls are made only while idle/reconciling so progress polling does not create API traffic or race the running state machine.

## 2026-08-25 — Release deployer is owned by Windows Task Scheduler

**Decision**

After a V3 Release has passed metadata, SHA-256, safe-extraction and manifest validation, the production helper is launched through a fixed Windows Task Scheduler task (`LOLDataSystem-ReleaseDeploy`) running as `SYSTEM` with highest privileges. `DETACHED_PROCESS` from the NSSM-hosted 6178 process is no longer the intended ownership boundary for the deployer.

The Task Scheduler launcher must write its real PowerShell PID to `deployment.pid` before the updater considers the deployment started. It also writes `launch.log` itself before invoking `Start-VerifiedReleaseUpdate.ps1`.

**Reasons**

- Production twice demonstrated that `CreateProcess` can return a PID for a detached PowerShell which disappears before `Start-Transcript` or any helper output, even though the V3 ZIP was fully downloaded and validated.
- A deployer that intentionally stops/replaces its own host service needs a lifecycle owner outside that service process tree. Task Scheduler is a Windows system service designed to own such independent jobs.
- Process creation success, task registration success, and task-run acceptance are not sufficient liveness proof; a helper-originated PID handshake is observable evidence that the intended PowerShell actually started.

**Consequences**

- The task action contains only local staging paths and never includes the GitHub Token.
- A fixed task name is overwritten on later updates, avoiding unbounded scheduled-task accumulation.
- `deployment.pid`, `launch.log`, and `update.log` form separate evidence layers: startup handshake, launcher/helper diagnostics, and formal V3 deployment transcript.
- The existing status machine continues to use the real deployment PID plus current production commit to decide `deploying`, `complete`, or `failed`.
- Failure to register/run Task Scheduler or receive the PID handshake is a launch failure and must not be shown as `scheduled`.
- A deployment-launch failure does not invalidate an already verified V3 ZIP; retry should reuse staging rather than redownload the asset.

## 2026-08-28 — Configuration semantics are one runtime/control-plane contract

**Decision**

A configurable behavior has one canonical meaning across runtime logic, WebUI, admin/query APIs, defaults/migrations, and documentation. Configuration precedence and inheritance are part of that contract, not implementation details that each surface may re-create independently.

For effective values, an explicit group override must be distinguishable from a value inherited from the global/default layer. Feature/profile settings may only be masked when the canonical precedence contract says so, not merely because an already-resolved group object happens to contain the inherited value.

**Reasons**

- The 2026-08-28 GroupGuard audit found `queryCommandProfiles.lol_battle.outputFormat="image"` and `global.lolQueryOutputFormat="forward"` while the WebUI presented the profile value but runtime battle delivery still selected `forward` for a group without an explicit output override.
- WebUI `commandOut()` and runtime `resolveQueryOutputFormat()` had evolved different precedence semantics. The same saved configuration therefore produced different answers depending on which surface interpreted it.
- A control panel that displays a different effective value from runtime is operationally worse than an obvious error because it makes a correct operator configuration look ineffective.

**Consequences**

- Runtime and WebUI/API effective previews must use the same precedence contract and, where practical, the same server-side resolver or resolved value/source.
- Changes to configurable runtime behavior must update every affected control-plane surface in the same task/PR.
- Regression tests for changed configuration behavior must cover relevant global, feature/profile, explicit group override, and inherited/no-override cases and assert parity between runtime and WebUI/API effective values.
- Issue #98 tracks the current GroupGuard query-output precedence defect; production configuration is not force-overwritten as a workaround.
## 2026-08-31 — GroupGuard queue trace is part of the API-to-QQ latency contract

### Decision

Keep `query-delivery-timing.v1` optional in the API response and carry the
sanitized values into GroupGuard. Define queued-delivery boundaries as T5 queue
submission, T6 worker acquisition, T7 configured risk-delay completion, and
T8/T9 around the actual OneBot action. Keep direct forward delivery unchanged
and classify it as a direct transport path.

### Reason

The API-side timings alone cannot explain the known enqueue-to-OneBot interval.
The GroupGuard trace must expose queue wait, intentional delay, and OneBot
processing independently without changing latency policy or image transport.

### Consequences

Later optimization decisions can use `T6-T5`, `T7-T6`, and `T9-T8` instead of
guessing from a single plugin duration. Older GroupGuard clients ignore the
optional timing metadata, while the new client remains compatible with API
responses that do not include it.

## 2026-08-31 — Keep image-stage timings local and do not bypass intentional risk policy

### Decision

Record API render and asset stages as monotonic relative offsets, and record
GroupGuard payload preparation plus queue/OneBot stages with monotonic elapsed
durations. Do not remove the configured query send queue or inherited random
risk delay solely because it appears in the end-to-end number.

### Reason

The API and GroupGuard clocks are separate hosts, so absolute cross-process
stage timestamps would imply precision that is not available. Existing
production evidence shows the queue/risk interval is material, but the delay
is an intentional shared anti-risk policy rather than an accidental image
download wait. A timing fix must not silently change that policy.

### Consequences

- `meta.timing.api_stage_offsets_ms` and image offset fields can locate render,
  asset and API payload work without pretending to be synchronized clocks.
- GroupGuard logs can compare queue wait, risk delay, payload preparation and
  OneBot processing using `performance.now()`.
- Any future latency-policy change needs its own explicit product/operations
  decision and regression evidence; this task only adds a safe ARAM cache-hit
  fast path that preserves TTL and balance freshness semantics.
