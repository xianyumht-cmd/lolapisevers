# Operations

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
11. An external PowerShell process runs the existing V3 deployer. The WebUI connection may drop while the service is switched.
12. Review the update log path shown in the WebUI if the service does not return normally.

### Interrupted update recovery

`update-state.json` is persistent evidence of the last known state, not proof that a worker still exists. Active worker state includes the current process PID, run id and heartbeat.

When a newly started 6178 process finds an old active download state whose worker does not belong to the current process, it changes the state to `interrupted` and keeps the existing `.part` file. The operator can then use **继续下载** or **重新连接**; a service restart is not required just to recover a download.

A live worker whose heartbeat becomes unexpectedly stale is surfaced as `stalled` so the UI offers reconnect/recovery instead of indefinitely presenting a healthy-looking download.

### Production-machine updater state

Default Windows directory:

`%PROGRAMDATA%\LOLDataSystem\updates`

Files include:

- `github-release-token.txt` — private-repository Release token; never committed or returned by the API.
- `update-state.json` — update state, worker identity, heartbeat and download progress without the token.
- `release-<id>-<sha>/` — verified staging directory, `.part` breakpoint, final ZIP and update log.

`LOLAPI_UPDATE_HOME` can override the updater directory. `LOLAPI_UPDATE_GITHUB_TOKEN` can supply the token from the environment instead of the token file.

Public mirror candidates are never given the private GitHub token. For a private repository they may fail authentication; the updater safely falls back to GitHub's authenticated API path rather than leaking credentials to a third party.

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
- unexpected number/name of V3 ZIP or metadata assets;
- metadata schema, filename or target commit mismatch;
- non-V3 package revision;
- missing UTF-8 parser or baseline-readiness flags;
- ZIP byte count or SHA-256 mismatch;
- ZIP path traversal;
- embedded manifest target/revision mismatch;
- missing candidate-test, automatic-rollback, offline-dependency, UTF-8 or baseline-readiness manifest flags;
- deployment script missing or introducing mandatory parameters the updater cannot resolve.

Resetting a partial download is confined to the updater home and a strictly validated V3 package filename. Pause/reconnect/resume never weaken the package integrity gates.

The V3 deployer remains the final authority for candidate testing, production backup, service switch, readiness verification and automatic rollback.
