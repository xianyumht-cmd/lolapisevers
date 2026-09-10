# Issue #103 — Runtime-aware V3 deployment and `.venv` ACL lifecycle

## Production topology verified on 2026-09-10

The Windows 10 production host was inspected with a read-only diagnostic before deployment.

- Runtime root / NSSM `AppDirectory`: `D:\project2\lolapisevers`
- Service: `LOLDataSystem`
- Base URL: `http://127.0.0.1:5001`
- Production health before upgrade: healthy
- Pre-upgrade `GET /lol/patch-status?date=2026-09-10`: HTTP 404
- Accessing the production `.venv\Scripts\python.exe` from the administrative deployment PowerShell raised `UnauthorizedAccessException`.

No credentials, tokens, cookies, environment-variable values, or raw configuration were retained in the repository.

## Root causes

Two separate V3 assumptions were invalid on the real production host.

1. Candidate bootstrap treated the production `.venv` as a required readable Python source. With `$ErrorActionPreference = "Stop"`, an ACL denial could abort before production was stopped.
2. During the production switch, the existing `.venv` was treated as an ordinary readable directory. A `.venv` inherited from a previous protected deployment identity could therefore fail at the backup/swap step.

The second issue also created a recurrence risk: moving a candidate `.venv` into production without normalizing its ACL could preserve deployment-identity-specific permissions and make the next maintenance run fail.

## Permanent V3 behavior

The canonical V3 build now applies two post-build artifact hardening passes after the existing Windows PowerShell 5.1 native-process patch.

### Runtime bootstrap

`Patch-V3-RuntimeBootstrapAcl.ps1`:

- prefers the Python executable owning the active HTTP listener;
- treats an unreadable production `.venv` as a non-fatal fallback miss;
- retains system `python.exe` / `py.exe` fallback;
- preserves the candidate-tests-before-stop and automatic-rollback gates.

### Production `.venv` lifecycle

`Patch-V3-ProductionVenvAcl.ps1`:

- runs only in the production-switch phase after the service stop;
- takes administrative ownership when needed;
- grants recursive full control to well-known Administrators SID `S-1-5-32-544` and SYSTEM SID `S-1-5-18`;
- repairs the existing production `.venv` before moving it to the rollback backup;
- normalizes the newly installed production `.venv` immediately after candidate installation;
- fails closed and leaves the existing V3 automatic rollback semantics active if ACL normalization cannot be completed.

The use of well-known SIDs avoids localized Windows account-name assumptions.

## Real-host validation

The CI-generated r4 candidate was exercised on the same Windows 10 production host on 2026-09-10.

Observed result:

- 484 candidate tests passed before production stop.
- Existing production `.venv` ACL normalization: PASS.
- Immutable source switch to `6e759fb4f134674a73ca6732ed51ad73bd0e682a`: PASS.
- Installed production `.venv` ACL normalization: PASS.
- Windows service restart: PASS.
- `/livez`: HTTP 200.
- required dependencies: `mysql=up; so1_browser=up`.
- SO1 session: authenticated.
- `/readyz`: HTTP 200.
- build-info commit: `6e759fb4f134674a73ca6732ed51ad73bd0e682a`.
- delivery shard verification: PASS.
- delivery ARAM verification: PASS.
- Git HEAD verification: PASS.
- overall post-switch verification: `status=pass`, `degraded=false`.
- `GET /lol/patch-status?date=2026-09-10`: verified as patch `26.18`, update day.

Rollback backup from the successful deployment is retained under the normal `lolapisevers.deploy-backups` mechanism.

## Regression protection

`tests/test_v3_runtime_venv_acl_workflow.py` requires the canonical V3 workflow to:

- apply the native-process patch first, then runtime-bootstrap ACL patch, then production-venv ACL lifecycle patch;
- require all runtime/ACL metadata and manifest flags;
- verify the expected deployment markers and forbidden old ACL-sensitive probes.

The temporary Issue #103 diagnostic report and one-off CI workflow are intentionally removed before merge; this document is the sanitized permanent record.
