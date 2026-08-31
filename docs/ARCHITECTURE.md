# Architecture

## Active production query delivery topology (verified 2026-08-31)

The production deployment is split across two hosts. `192.168.3.121` runs the
GroupGuard/SnowLuma/OneBot side, while `192.168.3.100:5001` runs the LOL API
and image renderer. Port 6178 on 100 is a control/update API, not the query
data path.

```text
QQ group message
      |
      v
SnowLuma OneBot WS :3001
      |
      v
GroupGuard intranet plugin (121)
      | POST /api/v1/groupguard/query
      v
LOLDataSystem :5001 (100)
      | query cache / upstream snapshot policy
      | Pillow render + local decorative asset cache
      | base64 image delivery envelope
      v
GroupGuard validates SHA-256, maps image to base64://, and enqueues send
      | external_query queue, group mode, concurrency 2, risk delay
      v
SnowLuma OneBot transport -> QQ
```

The active battle, shard and ARAM paths use the channel-neutral delivery
contract. An image is returned inside the JSON envelope as a base64 segment;
there is no public image URL, local file path, or second GroupGuard download
in this path. Older direct image-URL handlers remain in source for migration
review but are not the active `builtin.query.*.intranet` route.

The latency boundaries are intentionally separate:

- business/query data latency: upstream request, parser, result cache and snapshot fallback;
- image preparation latency: final-image cache lookup, decorative asset lookup/refresh, Pillow render and PNG encoding;
- transport latency: JSON/base64 transfer, GroupGuard decode/hash/plan construction, send queue delay and OneBot response.

The API now returns sanitized `meta.timing` fields for the first two
boundaries. GroupGuard keeps the cross-process trace through T0 plugin receive,
T1/T2 API request/response, T3 plan decode, T4 payload ready, T8 send start and
T9 send completion. This prevents the existing `plugin_execution_result`
duration from being mistaken for end-to-end delivery time.

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
