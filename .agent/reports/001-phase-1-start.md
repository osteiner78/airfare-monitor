# 001 Phase 1 — Start Report

## Scope

Implementing Phase 1: database schema, initialization, and all CRUD functions in `backend/db.py`. The scaffold stubs are in place; all 18 tests in `tests/test_db.py` currently fail with `NotImplementedError` from `init_db` — the correct failure mode.

## Tests to turn green

All 18 tests in `tests/test_db.py`:
- 4 schema/init tests (WAL mode, table existence)
- 10 CRUD behavioral tests (tracker create/get/list/update/delete, snapshot create, cascade, history, summaries)
- 4 failure-mode tests (None returns for missing IDs, no-raise on missing delete)

## Pre-work observations

- `pyproject.toml` has `asyncio_mode = "auto"` — test functions don't need `@pytest.mark.asyncio`.
- `conftest.py` injects `AIRFARE_DB_PATH` via monkeypatch before calling `init_db` — the `get_db_path()` helper is already in place.
- `db_conn` fixture uses `aiosqlite.Row` factory, so rows support both index and column-name access.
- `test_update_tracker_sets_active_to_false` checks `fetched["active"] is False or fetched["active"] == 0` — SQLite stores booleans as integers, so either is acceptable.
- `test_get_price_history_returns_empty_for_tracker_with_no_snapshots` accepts `[] or {}` — will return `[]` (list is cleaner for an empty history).
- No new dependencies needed beyond what's already in `requirements.txt`.

## Plan

Tasks 1.6–1.10 in sequence: schema DDL, tracker CRUD, snapshot+prices, history+summaries, `data/.gitkeep`.
