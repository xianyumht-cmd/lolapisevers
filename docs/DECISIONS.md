# Technical decisions

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
