# Operations

## Read-only production query-chain audit

Use this checklist before changing image delivery or declaring an upstream
latency problem fixed. The production working tree on 100 remains read-only;
the 121 container data directory is also read-only during an audit.

1. Verify the actual service/process/listener owners on 100. The expected query listener is `0.0.0.0:5001` under `LOLDataSystem`; 6178 is a separate control service.
2. Verify the 121 containers and listeners. The expected bot side is `groupguard-snowluma` plus `snowluma`, with OneBot WS on 3001; 121 should not be expected to listen on 5001.
3. Read only the safe build-info, health/readiness and query-observability surfaces. Do not export environment values, cookies, raw messages, request parameters or payload JSON.
4. Confirm the active `lolApiBaseUrl`, query profiles, queue mode/concurrency, and the `external_query` risk-delay override. A missing scene override means the global 500–1500ms delay applies.
5. For a controlled comparison, call the API from 121 with text and image preferences, repeat only after recording whether business and final-image caches are warm, and compare API time, PNG bytes, base64 characters, cache state and asset state.
6. For end-to-end evidence, aggregate `bot_send_events` read-only by scene, media flag and status. Use `sent_at - queued_at` only for rows with a successful send timestamp; separately report configured random delay. Failed rows must not be treated as valid latency samples.

The API timing trace is `query-delivery-timing.v1` under the response `meta`.
The GroupGuard trace is `query-delivery-timing.v1` in its internal structured
response metadata and log event. For queued text/image delivery, T5/T6/T7/T8/T9
are placed at queue submission, worker acquisition, risk-delay completion, and
the actual OneBot action boundaries. Direct forward delivery remains direct and
does not claim queue timing. Neither trace contains credentials, group IDs, or
raw query content. A production restart, configuration change, container
rebuild or deployment is outside an audit and needs separate explicit
authorization.

## GitHub Release production update

### First installation of the updater

The production version that predates the Release updater cannot update itself. Deploy the first updater-capable commit with the existing verified V3 deployment package and the normal production-safe procedure. Do not replace the production source tree manually.

If the installed updater itself is blocked by a known download-control bug, use a CI-verified local V3 bootstrap package containing the exact V3 ZIP and `.metadata.json`. The bootstrap must verify filename, byte count, SHA-256, package revision and embedded manifest before invoking the normal `Deploy-FullBugRepairSafe.ps1`; it is only a transport/bootstrap path, not a weaker deployment path.

### Normal later update

1. Merge a tested change to `master`.
2. `.github/workflows/build-production-safe-deployment-v3.yml` runs the full target tests, PowerShell parsing, dependency audit, V3 package build and package integrity checks.
3. The build job uploads the ZIP and `.metadata.json` as a CI artifact.
4. On a `master` push only, a separate `publish-release` job downloads that verified artifact and publishes it as the latest GitHub Release.
5. Open the 6178 `/system` page and use **检查更新**.
6. For the private repository, configure a read-only GitHub token once. The value is not returned by the API or page.
7. Click **一键升级** and confirm. The start request only creates a background update worker and returns immediately; the page then polls local state.
8. During download, use **暂停下载** to preserve the `.part` file, **继续下载** to resume it, **重新连接** to close the current HTTP connection and reconnect from the same breakpoint, or **清空断点重下** to intentionally delete the current target package/partial and restart from byte 0.
9. The downloader uses 64 KiB chunks for responsive progress/control checks. In addition to socket read timeout, a low-speed window prevents trickle traffic from remaining fake-alive forever. Defaults are about 30 seconds below 32 KiB/s; `LOLAPI_UPDATE_LOW_SPEED_WINDOW` and `LOLAPI_UPDATE_MIN_BPS` can tune this.
10. The updater verifies metadata, target commit, package revision, SHA-256, safe ZIP paths and embedded manifest safety flags before starting the deployer.
11. On Windows, the verified `Start-VerifiedReleaseUpdate.ps1` helper is owned by Windows Task Scheduler rather than relying only on a `DETACHED_PROCESS` grandchild of the NSSM service. The updater creates/overwrites the fixed task `LOLDataSystem-ReleaseDeploy`, runs it as `SYSTEM` with highest privileges, and starts it immediately.
12. The Task Scheduler launcher writes its real PowerShell PID to `deployment.pid` before doing deployment work. The updater waits for this handshake; no PID means the deployment was not actually started and the state is failed rather than scheduled.
13. After the handshake, the launcher writes the first `launch.log` line and redirects helper output there. The deployer's PowerShell transcript remains `update.log`. The launcher process is owned by Task Scheduler, so it survives 6178/NSSM service-tree replacement during the V3 switch.
14. `scheduled` is only a transition state. `/admin/update/status` checks the deployment PowerShell PID and the current production commit: live PID => `deploying`; dead PID + target commit active => `complete`; dead PID + old commit => `failed`. The WebUI keeps polling through `scheduled/deploying` instead of stopping at “process started”.
15. If the helper fails before `Start-Transcript`, use `launch.log`; if it entered the deployer, use `update.log`. A valid Task Scheduler start must never leave both the PID handshake and launch diagnostics absent.
16. Candidate preflight native processes (Python/Node) must not be invoked directly under WinPS 5.1 with `$ErrorActionPreference = "Stop"`. The verified V3 artifact uses a `System.Diagnostics.Process` wrapper that captures stdout/stderr into the transcript and treats only a nonzero native ExitCode as failure. Benign warnings on stderr remain visible but cannot abort a successful command.

### Private Release download acceleration

The repository is private, so public GitHub proxy services are only best-effort candidates. They are probed without credentials and are never given the GitHub Release Token. A public proxy failing with 404/403/timeout is expected and must not cause credential forwarding.

For the private Release fast path:

1. The updater authenticates only to the official GitHub asset API with the read-only token and requests the ZIP asset with redirects disabled.
2. A 30x redirect is accepted only when the destination host is an allowlisted GitHub-owned asset host: `release-assets.githubusercontent.com` or `objects.githubusercontent.com`.
3. The temporary signed asset URL remains in process memory. The full signed URL is not written to `update-state.json`, logs, task arguments or public mirror requests.
4. The official signed CDN candidate defaults to 6 parallel Range requests. `LOLAPI_UPDATE_CDN_CONNECTIONS` may tune this from 2 through 8.
5. Existing contiguous `.zip.part` bytes remain the resume prefix. Parallel segments are temporary files; only a provably contiguous prefix is committed back to `.part` if pause/reconnect/failure interrupts the parallel transfer.
6. Every Range response must be HTTP 206 with an exact `Content-Range`. If the CDN does not support the required Range semantics, the updater falls back to a single connection against the same official signed URL and continues from the contiguous `.part` prefix.
7. The final ZIP is never trusted merely because the CDN transfer completed. The official Release metadata SHA-256, safe ZIP extraction and embedded V3 manifest checks remain mandatory before Task Scheduler deployment starts.

China-friendly public acceleration prefixes may be added or removed over time; runtime parallel probing and failover are the source of truth, not a hard-coded assumption that any free proxy will stay healthy.

### Release freshness and downgrade guard

Idle updater state is not allowed to trust a persisted `failed`, `interrupted`, `stalled` or old completed target as the newest release forever. When there is no live worker or deployment process, **检查更新** refreshes GitHub `releases/latest` and its metadata, then checks the commit relationship using GitHub's official Compare API.

The relation is evaluated as `current...target`:

- `identical` — current production and Release target are the same commit; no update is offered.
- `ahead` — the Release target is ahead of current production; this is the only relation that enables a normal forward one-click update.
- `behind` — the Release target is already contained in current production; the Release has not caught up and the updater must not downgrade production.
- `diverged` — the histories have split; automatic update is blocked.
- API error / unknown relationship — fail closed and block the update rather than guessing.

A previous failed task remains available only as `last_update_state` diagnostic history. It must not replace the freshly queried Release name/target in the idle status response.

The same relationship guard applies before **一键升级**, **继续下载**, **重新连接**, and **清空断点重下**. A stale `.part` or verified ZIP is never a reason to install a target that is behind the current production commit. If the saved target is behind, diverged, or cannot be verified, recovery actions are blocked until a safe forward Release exists.

Active worker and deployment polling remain local-only. The updater does not call GitHub Compare on every 1.2-second progress poll; GitHub refresh/compare happens only when the updater is idle or reconciling a finished task.

### Interrupted update recovery

`update-state.json` is persistent evidence of the last known state, not proof that a worker still exists. Active worker state includes the current process PID, run id and heartbeat.

When a newly started 6178 process finds an old active download state whose worker does not belong to the current process, it changes the state to `interrupted` and keeps the existing `.part` file. The operator can then use **继续下载** or **重新连接** only if that saved target is still a verified forward target; a service restart is not required just to recover a download.

A live worker whose heartbeat becomes unexpectedly stale is surfaced as `stalled` so the UI offers reconnect/recovery instead of indefinitely presenting a healthy-looking download.

Deployment is different from interrupted download. While the Task Scheduler-owned deployment PID is alive, download reset/reconnect controls are disabled so the verified package cannot be deleted and a second upgrade chain cannot be started underneath the active deployer.

A failed deployment does not invalidate an already verified final ZIP. If `downloaded_bytes == package_bytes`, SHA-256/manifest verification previously succeeded, and the saved target is still a safe forward target, retrying the deployment launcher should reuse the existing staging package rather than downloading the same 80+ MiB asset again.

### Production-machine updater state

Default Windows directory:

`%PROGRAMDATA%\LOLDataSystem\updates`

Files include:

- `github-release-token.txt` — private-repository Release token; never committed or returned by the API.
- `update-state.json` — update state, worker identity, heartbeat, deployment PID and download progress without the token.
- `release-<id>-<sha>/` — verified staging directory, `.part` breakpoint/final ZIP, `Start-VerifiedReleaseUpdate.ps1`, `Task-VerifiedReleaseUpdate.ps1`, `deployment.pid`, `launch.log` and `update.log`.

Task Scheduler uses the fixed task name `LOLDataSystem-ReleaseDeploy`; a later update replaces that task definition instead of creating an unbounded number of tasks.

`LOLAPI_UPDATE_HOME` can override the updater directory. `LOLAPI_UPDATE_GITHUB_TOKEN` can supply the token from the environment instead of the token file.

Public mirror candidates are never given the private GitHub token. For a private repository they may fail authentication; the updater safely falls back to the GitHub-owned signed asset/CDN path and then the authenticated API path rather than leaking credentials to a third party.

GitHub commit-relation checks use the same read-only token only against `api.github.com`; the token is never forwarded to public acceleration mirrors.

### Windows service restart verification

The `/system` **重启服务** action is not considered successful merely because an external `Restart-Service` command was launched.

1. Before scheduling restart, the controller reads `sc.exe queryex LOLDataSystem` and records the service PID.
2. The detached PowerShell restart is scheduled and the UI enters a waiting/verification state.
3. After 6178 returns, `/admin/service/status` reads the new service PID.
4. The restart is `verified` only when the service is `Running` and the PID is non-zero and different from the recorded PID.
5. If no PID replacement is observed within about 60 seconds, the result becomes `unverified`; the UI must not claim success.

Because NSSM can restart the supervisor and its 5001/6178 children within a few seconds, a browser page being reachable shortly after `Restart-Service` is normal and by itself proves neither success nor failure. PID replacement is the verification signal.

### Safety gates

The WebUI updater refuses to schedule deployment when any of these checks fail:

- non-Windows platform;
- latest Release unavailable or private-repository Token missing;
- current/target commit relation is `behind`, `diverged`, or cannot be safely confirmed as a forward update;
- unexpected number/name of V3 ZIP or metadata assets;
- metadata schema, filename or target commit mismatch;
- non-V3 package revision;
- missing UTF-8 parser, baseline-readiness, native Git stderr-safety, or native process stderr-safety flags;
- ZIP byte count or SHA-256 mismatch;
- ZIP path traversal;
- embedded manifest target/revision mismatch;
- missing candidate-test, automatic-rollback, offline-dependency, UTF-8, baseline-readiness, native Git stderr-safety, or native process stderr-safety manifest flags;
- deployment script missing or introducing mandatory parameters the updater cannot resolve;
- Windows Task Scheduler cannot register/run the verified helper or no `deployment.pid` handshake is observed.

The Task Scheduler action contains only local verified staging paths; the GitHub token is never placed in task arguments, task files or launch logs.

Resetting a partial download is confined to the updater home and a strictly validated V3 package filename. Pause/reconnect/resume never weaken the package integrity or commit-relationship gates.

The V3 deployer remains the final authority for candidate testing, production backup, service switch, readiness verification and automatic rollback.
