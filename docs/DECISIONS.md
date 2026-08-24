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

## 2026-08-24 — ARAM recommendations must not invent combination win rates

**Decision**

The sea-rune image may derive practical pick directions from single-augment win rate and popularity, but derived recommendations must be labeled as such and must not be displayed as measured three-augment combination win rates.

**Reasons**

The current OP.GG upstream parser supplies per-augment performance/popularity data. Combining those values mathematically would not create a statistically valid observed combination win rate.

**Consequences**

- The image groups augments by quality and shows single-augment metrics directly.
- “稳健首选 / 高胜上限 / 热门容错” are decision aids derived from single-augment data.
- The rendered image explicitly states that those routes are not measured three-augment combination win rates.
