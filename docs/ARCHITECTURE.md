# Architecture

## Query image latency boundary

Business/query data and decorative image assets have different freshness requirements and therefore different request boundaries.

1. Business services fetch player history, ranks, augment statistics and other query data through their existing upstream/snapshot policy. Image optimization must not replace current business data with a long-lived image cache.
2. Once a business payload is available, renderers resolve profile/champion/item/augment artwork from the local image cache first.
3. Missing decorative assets do **not** synchronously block the user query by default. The current render uses available local assets or a placeholder and schedules the missing CDN asset in a bounded process-wide background pool.
4. Background asset refresh uses single-flight per URL plus a short failure cooldown. Background failures are not written into the long-lived negative cache, so a temporary CDN failure can be retried later.
5. `IMAGE_ASSET_BLOCKING_FETCH_ENABLED=1` is an explicit maintenance/diagnostic escape hatch. Normal query rendering must not depend on it.
6. Battle PNGs use a short server-side final-image cache keyed only by fields that affect the visible render plus a renderer version and footer values. A changed business payload therefore gets a different cache key.
7. A battle render produced while required local image assets are still warming is returned immediately but is not stored in the final-image cache. After background refresh completes, the next query can render the complete artwork and then cache it.
8. HTTP responses remain `Cache-Control: no-store`; the server-side render cache is an implementation optimization and does not authorize clients or intermediaries to retain player query images.

The request path is therefore:

```text
third-party business/query data
        |
        v
short-lived final render cache ---- hit ---> return
        |
       miss
        v
local image asset cache
        | missing decorative asset
        +---------------------------> background CDN refresh
        |
        v
Pillow render -> latency-oriented PNG encode -> return
                                      |
                                      +-> cache only when required assets are complete
```

This boundary deliberately optimizes image latency without claiming that a slow third-party business API can be made sub-second locally.

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
