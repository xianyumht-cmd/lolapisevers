# Lanzou monitor module boundaries

The Lanzou update monitor is intentionally split by responsibility. Keep these boundaries when adding monitor features or fixing delivery behavior.

## Ownership

- `lanzou_update_push_api_server/monitor.py`
  - owns `LanzouMonitorService`
  - owns scheduling, scan orchestration, guard/rebaseline decisions, event construction, and callback delivery
  - remains the compatibility import surface for `LanzouMonitorService`, `StateStore`, `compare_snapshots`, `STATE_SCHEMA_VERSION`, and the existing private error helpers used by current tests/callers
- `lanzou_update_push_api_server/monitor_state.py`
  - owns persisted monitor state, schema migration, snapshot/event/pending-delivery storage, watcher reconciliation, and guard candidates
- `lanzou_update_push_api_server/monitor_diff.py`
  - owns provider-aware/canonical snapshot comparison
- `lanzou_update_push_api_server/monitor_errors.py`
  - owns safe error classification and removal of legacy free-form error context before persistence

## Compatibility rules

Existing imports from `lanzou_update_push_api_server.monitor` must keep working. Moving implementation ownership must not force API, WebUI, tests, or external callers to change imports just to follow an internal refactor.

The callback implementation intentionally remains in `monitor.py` for now. Existing tests and extensions patch `lanzou_update_push_api_server.monitor.requests.post`; moving callback transport requires an explicit compatibility plan rather than silently changing that patch seam.

## Safety rules

- State schema changes belong in `monitor_state.py` and require migration coverage.
- Snapshot identity/diff behavior belongs in `monitor_diff.py` and requires same-provider plus cross-provider regression coverage.
- Error details written to state must pass through the safe error helpers; raw URLs, headers, bodies, query parameters, exception messages, or credentials must not be persisted.
- Scan guard, rebaseline, pending-delivery, and snapshot-commit semantics are behavior contracts. Module extraction must preserve them.
- Structural tests must fail if `StateStore` or `compare_snapshots` implementations are copied back into `monitor.py`.

## Current refactor boundary

This split is deliberately behavior-preserving. It does not change API routes, WebUI behavior, notification payloads, scan cadence, provider selection, callback acknowledgement rules, or production deployment behavior.
