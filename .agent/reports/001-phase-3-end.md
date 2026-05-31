# 001 Phase 3 — End Report

## What was built

- **Task 3.2**: `backend/models.py` — `TrackerCreate` (Pydantic, date format validation), `TrackerUpdate`, `TrackerResponse` (`active: bool` ensures correct JSON serialization).
- **Tasks 3.3–3.4**: `backend/scheduler.py` — `search_and_store()` (full implementation: calls sources, creates snapshot, stores prices), `add_tracker_job()` and `remove_tracker_job()` with safe no-ops when `scheduler is None`.
- **Tasks 3.5–3.7**: `backend/api.py` — All 7 REST endpoints with correct status codes, Pydantic validation, scheduler integration via `import backend.scheduler` (module-reference pattern required by conftest mock).
- **Tasks 3.8–3.9**: `backend/main.py` — Lifespan handler (init DB, create/start scheduler, rebuild jobs on restart, shutdown cleanly) plus HTTP middleware for test compatibility.

## Verification output

```
collected 15 items

tests/test_api.py::test_get_trackers_returns_empty_list_initially PASSED
tests/test_api.py::test_post_trackers_returns_201_with_tracker_id PASSED
tests/test_api.py::test_post_trackers_adds_tracker_visible_in_list PASSED
tests/test_api.py::test_get_tracker_by_id_returns_tracker PASSED
tests/test_api.py::test_get_tracker_returns_404_for_unknown_id PASSED
tests/test_api.py::test_patch_tracker_sets_active_to_false PASSED
tests/test_api.py::test_delete_tracker_returns_204 PASSED
tests/test_api.py::test_delete_tracker_removes_tracker_from_list PASSED
tests/test_api.py::test_delete_tracker_returns_404_for_unknown_id PASSED
tests/test_api.py::test_get_history_returns_empty_flights_for_new_tracker PASSED
tests/test_api.py::test_post_search_returns_200 PASSED
tests/test_api.py::test_post_trackers_returns_422_when_origin_is_missing PASSED
tests/test_api.py::test_post_trackers_returns_422_when_destination_is_missing PASSED
tests/test_api.py::test_post_trackers_returns_422_when_depart_date_is_missing PASSED
tests/test_api.py::test_post_trackers_returns_422_when_depart_date_format_is_invalid PASSED

15 passed in 0.34s
```

Full regression (54 tests, -k "not slow"): 52 passed, 2 failed (both in `test_notifications.py` — Phase 6 API endpoints not yet implemented, expected).

Smoke test: `GET /api/trackers` → `[]`, `POST /api/trackers` → `{"id": 1, ...}` ✓

## Key deviation: httpx 0.28 doesn't trigger ASGI lifespan

The conftest assumes `AsyncClient` with `ASGITransport` triggers the FastAPI lifespan, but httpx 0.28's `ASGITransport` only sends HTTP scopes — it never sends the `type="lifespan"` ASGI scope. The lifespan's `init_db()` therefore never ran during tests.

**Fix**: Added a HTTP middleware (`ensure_db_initialized`) that calls `init_db(path)` on the first request for each unique DB path. The `_initialized_paths` set deduplicates across requests. The lifespan is kept for production use (uvicorn triggers it correctly). Since `search_and_store` is mocked and the scheduler is `None` in tests, `add_tracker_job`/`remove_tracker_job` are safe no-ops.

## Test gaps

None. All 15 orchestrator tests pass. No new tests added.

## Follow-ups

- `get_tracker_summaries()` is used for `GET /api/trackers` — it returns dicts with `best_price` and `last_searched_at` fields that aren't in `TrackerResponse`. This works for the tests (which only check `len`) but the frontend will need to handle these extra fields.
- The `_initialized_paths` set in `main.py` persists across the test session (module-level). This is intentional — each test uses a unique temp path.

## Confidence

**certain** — 15/15 Phase 3 tests pass, smoke test validates live server behavior.
