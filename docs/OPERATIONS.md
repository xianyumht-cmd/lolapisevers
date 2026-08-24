# Operations

## GitHub Release production update

### First installation of the updater

The production version that predates the Release updater cannot update itself. Deploy the first updater-capable commit with the existing verified V3 deployment package and the normal production-safe procedure. Do not replace the production source tree manually.

### Normal later update

1. Merge a tested change to `master`.
2. `.github/workflows/build-production-safe-deployment-v3.yml` runs the full target tests, PowerShell parsing, dependency audit, V3 package build and package integrity checks.
3. The build job uploads the ZIP and `.metadata.json` as a CI artifact.
4. On a `master` push only, a separate `publish-release` job downloads that verified artifact and publishes it as the latest GitHub Release.
5. Open the 6178 `/system` page and use **检查更新**.
6. For the private repository, configure a read-only GitHub token once. The value is not returned by the API or page.
7. Click **一键升级** and confirm.
8. The updater verifies metadata, target commit, package revision, SHA-256, safe ZIP paths and embedded manifest safety flags before starting the deployer.
9. An external PowerShell process runs the existing V3 deployer. The WebUI connection may drop while the service is switched.
10. Review the update log path shown in the WebUI if the service does not return normally.

### Production-machine updater state

Default Windows directory:

`%PROGRAMDATA%\LOLDataSystem\updates`

Files include:

- `github-release-token.txt` — private-repository Release token; never committed or returned by the API.
- `update-state.json` — last scheduled update metadata without the token.
- `release-<id>-<sha>/` — verified staging directory and update log.

`LOLAPI_UPDATE_HOME` can override the updater directory. `LOLAPI_UPDATE_GITHUB_TOKEN` can supply the token from the environment instead of the token file.

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

The V3 deployer remains the final authority for candidate testing, production backup, service switch, readiness verification and automatic rollback.
