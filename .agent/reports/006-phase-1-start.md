# 006 — Start Report

## Scope

Three phases: logging infrastructure (DB table + CRUD + wire into scheduler/pages/api), monitoring dashboard (/monitor page with auto-refresh), and tests.

## Tests to turn green

6 tests in `tests/test_logging.py` — all currently fail: 5 ImportError (functions not yet implemented), 1 AssertionError (/monitor route 404).

## Pre-work observations

- 94 existing tests pass — solid baseline.
- `insert_log` must accept `level`, `event`, `tracker_id` (nullable), `message`.
- `get_recent_logs(limit)` returns newest first (ORDER BY id DESC).
- `/monitor` route returns full HTML page; `/monitor/logs` returns `<tbody>` rows partial for HTMX polling.
- Logging is wired at call sites (pages.py, api.py, scheduler.py), not inside DB CRUD functions.
