# 001 Phase 1 — End Report

## What was built

- **Task 1.6–1.9**: Implemented `backend/db.py` with full schema DDL (`init_db`), tracker CRUD (`create_tracker`, `get_tracker`, `list_trackers`, `update_tracker`, `delete_tracker`), snapshot + prices (`create_snapshot`, `insert_flight_prices`, `get_latest_snapshot`, `get_previous_snapshot`), and history/summaries (`get_price_history`, `get_tracker_summaries`). Notification CRUD (`create_notification`, `list_notifications`, `delete_notification`) and the notifications table were included in the schema since the stubs were in the scaffold and the Phase 6 tests will need them.
- **Task 1.10**: Created `data/.gitkeep` to ensure the `data/` directory is tracked in git.

## Verification output

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
asyncio: mode=Mode.AUTO
collected 18 items

tests/test_db.py::test_wal_mode_enabled_after_init PASSED
tests/test_db.py::test_trackers_table_exists_after_init PASSED
tests/test_db.py::test_snapshots_table_exists_after_init PASSED
tests/test_db.py::test_flight_prices_table_exists_after_init PASSED
tests/test_db.py::test_create_tracker_returns_dict_with_id PASSED
tests/test_db.py::test_create_tracker_stores_all_provided_fields PASSED
tests/test_db.py::test_list_trackers_returns_empty_list_when_no_trackers_exist PASSED
tests/test_db.py::test_get_tracker_returns_tracker_by_id PASSED
tests/test_db.py::test_update_tracker_sets_active_to_false PASSED
tests/test_db.py::test_delete_tracker_removes_the_row PASSED
tests/test_db.py::test_delete_tracker_cascades_to_snapshots PASSED
tests/test_db.py::test_create_snapshot_returns_dict_with_id PASSED
tests/test_db.py::test_get_price_history_returns_empty_for_tracker_with_no_snapshots PASSED
tests/test_db.py::test_get_tracker_summaries_returns_empty_list_when_no_trackers PASSED
tests/test_db.py::test_get_tracker_returns_none_when_id_does_not_exist PASSED
tests/test_db.py::test_get_tracker_returns_none_for_zero_id PASSED
tests/test_db.py::test_get_tracker_returns_none_for_negative_id PASSED
tests/test_db.py::test_delete_tracker_on_missing_id_does_not_raise PASSED

18 passed in 0.10s
```

Schema spot-check:
```
journal: wal
trackers cols: ['id', 'origin', 'destination', 'depart_date', 'return_date', 'currency', 'interval_minutes', 'top_n', 'active', 'created_at']
```

## Deviations from plan

- **Notifications table included early**: The plan puts the `notifications` table in Phase 6, but the stubs for notification CRUD were already in the scaffold. I included the table DDL and CRUD now to avoid `init_db` needing to change between phases (which would require migration logic). The Phase 6 tests will benefit from this. No test currently covers the table existence, so no test was affected.

## Test gaps

None. All 18 orchestrator tests pass. No new tests added.

## Follow-ups

- `insert_flight_prices` takes a list of dicts — callers (Phase 3 scheduler) will need to construct these dicts from `FlightResult` objects.
- `get_tracker_summaries` computes `best_price` via a correlated subquery. Adequate for v1 volumes; an indexed denormalized column would be faster at scale.

## Confidence

**certain** — all 18 tests pass, WAL mode verified, schema matches plan exactly.
