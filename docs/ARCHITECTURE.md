# Architecture

## Release self-update execution boundary

The 6178 control process owns Release discovery, download, pause/resume/reconnect, SHA-256 verification, safe extraction, and V3 manifest validation.

After verification, the deployment boundary moves outside the NSSM service process tree:

1. The updater writes `Start-VerifiedReleaseUpdate.ps1` into the verified Release staging directory.
2. `release_task_scheduler.py` writes `Task-VerifiedReleaseUpdate.ps1` beside it.
3. Windows Task Scheduler creates/overwrites the fixed `LOLDataSystem-ReleaseDeploy` task and runs it as `SYSTEM` with highest privileges.
4. The Task Scheduler-owned PowerShell writes `deployment.pid` before any deployment delay, then writes `launch.log` and invokes the verified helper.
5. The verified helper starts the formal V3 deployer, whose transcript is `update.log`.
6. The V3 deployer may stop and replace the `LOLDataSystem` service without losing its own launcher, because Task Scheduler—not the service being replaced—owns the deployment process.
7. After 6178 returns, status reconciliation uses the real deployment PID plus current build commit to classify `deploying`, `complete`, or `failed`.

The task action contains no GitHub credential. GitHub Release Token use ends at the authenticated GitHub API/download boundary; the scheduler receives only local verified staging paths.
