# 017 Phase 3 — End Report

## What was built

- **3.1** `backend/db.py` `_SCHEMA`: added `kayak_enabled INTEGER NOT NULL DEFAULT 0` and `kayak_next_due_at TEXT` to the `trackers` table. Fresh DBs only (every test via the `db_path`/`client` fixtures) — the live DB `ALTER TABLE` was **not** run; it needs explicit user confirmation per this project's CLAUDE.md and is a separate, deliberate follow-up step before deploying.
- **3.2/3.3** `backend/scheduler.py`: added `_jittered_kayak_interval_minutes(base_minutes)` (±20% jitter via `random.uniform(0.8, 1.2)`, floored at `1.0` so tiny bases can't go non-positive) and `_kayak_due(next_due_at, now)` (pure, `None` → due now). Both module-level, no scheduler dependency.
- **3.4** `backend/scheduler.py` `search_and_store`: gained a `delay: bool = True` parameter and a Kayak block inserted after the existing source loop and before `create_snapshot`. Gated by `tracker["kayak_enabled"]` and `_kayak_due(...)`. On entry: optional `asyncio.sleep(random.uniform(0, 900))` pre-render delay (skippable via `delay=False`), then `KayakSource().search(...)`, results extended into the shared `results` list so they land in the same snapshot as fli's rows. `last_error`/`last_error_level` from the Kayak instance are logged as `kayak_search_error` (distinct event name from the main loop's `search_error`). Any exception is caught and logged the same way. A `finally` block always advances `kayak_next_due_at` (success or failure) so a blocked run can't hot-retry next tick.
- **3.5** `backend/sources/__init__.py`: added a one-line comment explaining why `KayakSource` is deliberately absent from `get_sources()`.
- **3.6** `backend/models.py`: added `kayak_enabled: bool | None = None` to `TrackerUpdate` and `kayak_enabled: bool` to `TrackerResponse`.
- **3.7** Confirmed (not modified): `update_tracker_endpoint` in `backend/api.py` is generic over `TrackerUpdate`'s fields via `model_dump(exclude_none=True)`, so it accepts `kayak_enabled` with no code change.
- **3.8** `backend/pages.py`: added `PATCH /trackers/{tracker_id}/toggle-kayak`, mirroring `toggle_tracker_detail` — flips `kayak_enabled`, logs `kayak_enabled`/`kayak_disabled`, re-renders `partials/detail_page.html`. No job-scheduling calls (no separate Kayak job exists). `frontend/templates/partials/detail_page.html` gained a small badge + toggle button next to the existing active/pause control, detail page only.
- **3.9** No `main.py` change — confirmed `_startup` already re-registers a job per active tracker, and Kayak now rides that job.

## Verification output

```
$ docker exec -w /app airfare-monitor python -m pytest tests/test_kayak_scheduling.py -v -k "not slow"
collected 21 items

tests/test_kayak_scheduling.py::test_create_tracker_defaults_kayak_enabled_to_false PASSED
tests/test_kayak_scheduling.py::test_tracker_kayak_enabled_can_be_turned_on PASSED
tests/test_kayak_scheduling.py::test_kayak_next_due_at_defaults_to_null PASSED
tests/test_kayak_scheduling.py::test_kayak_due_when_next_due_at_is_null PASSED
tests/test_kayak_scheduling.py::test_kayak_due_when_now_is_past_next_due_at PASSED
tests/test_kayak_scheduling.py::test_kayak_not_due_when_now_is_before_next_due_at PASSED
tests/test_kayak_scheduling.py::test_jittered_kayak_interval_stays_within_documented_bounds PASSED
tests/test_kayak_scheduling.py::test_jittered_kayak_interval_is_not_always_the_same_value PASSED
tests/test_kayak_scheduling.py::test_jittered_kayak_interval_handles_small_base_without_going_non_positive PASSED
tests/test_kayak_scheduling.py::test_search_and_store_puts_kayak_and_fli_results_in_the_same_snapshot PASSED
tests/test_kayak_scheduling.py::test_snapshot_results_count_includes_both_sources PASSED
tests/test_kayak_scheduling.py::test_notifications_evaluate_against_cross_source_minimum_price PASSED
tests/test_kayak_scheduling.py::test_search_and_store_does_not_call_kayak_when_kayak_disabled PASSED
tests/test_kayak_scheduling.py::test_search_and_store_does_not_call_kayak_when_not_due PASSED
tests/test_kayak_scheduling.py::test_search_and_store_advances_next_due_at_after_a_successful_kayak_run PASSED
tests/test_kayak_scheduling.py::test_search_and_store_advances_next_due_at_after_a_failed_kayak_run PASSED
tests/test_kayak_scheduling.py::test_kayak_failure_still_stores_fli_results_and_creates_snapshot PASSED
tests/test_kayak_scheduling.py::test_kayak_failure_logs_kayak_search_error_at_its_own_level PASSED
tests/test_kayak_scheduling.py::test_kayak_exception_never_propagates_out_of_search_and_store PASSED
tests/test_kayak_scheduling.py::test_toggle_kayak_endpoint_flips_kayak_enabled PASSED
tests/test_kayak_scheduling.py::test_toggle_kayak_endpoint_returns_404_for_missing_tracker PASSED

21 passed in 3.51s
```

```
$ docker exec -w /app airfare-monitor python -m pytest tests/ -k "not slow"
FAILED tests/test_best_source.py::test_get_tracker_summaries_best_source_matches_cheapest_price_row
FAILED tests/test_best_source.py::test_get_tracker_summaries_best_source_updates_when_a_cheaper_source_appears
FAILED tests/test_best_source.py::test_get_tracker_summaries_best_source_is_none_when_no_snapshots
FAILED tests/test_best_source.py::test_best_source_is_deterministic_when_two_sources_tie_on_price
FAILED tests/test_best_source.py::test_results_table_source_label_falls_back_to_raw_value_for_unknown_source
5 failed, 284 passed, 3 deselected in 26.58s
```

The 5 remaining failures are all in `test_best_source.py`, which is Phase 4's test file (`best_source` correlated subquery + Source column templating) — untouched by this phase, exactly as expected. No test outside `test_kayak_scheduling.py`/`test_best_source.py` regressed. Baseline before this phase (confirmed by running the suite first): 19 failures in `test_kayak_scheduling.py` + 6 in `test_best_source.py` = 25 failed, 262 passed. Note: one `test_best_source.py` test (`test_results_table_shows_source_for_each_flight_row`) now incidentally passes — it doesn't assert anything Phase 3 code affects; not investigated further since it's Phase 4 scope and moving from fail→pass is not a regression.

## Commit

`[phase-3.1-3.9] Wire Kayak into the main search cycle` — see `git log`.

## Deviations from plan

- **APScheduler job-stacking mitigation (Risks section, not a numbered task):** the plan's risk note for `add_tracker_job` — "Set `max_instances=1`, `coalesce=True` and a `misfire_grace_time`" — turned out to already be this project's `AsyncIOScheduler()`'s library defaults. Verified at runtime: `AsyncIOScheduler()._job_defaults == {'misfire_grace_time': 1, 'coalesce': True, 'max_instances': 1}`. No code change made; noting this so the next reader doesn't wonder why `add_tracker_job` wasn't touched.
- No other deviations. All 3.1–3.9 tasks implemented as specified.

## Test gaps / new tests

- The two toggle-endpoint tests (`test_toggle_kayak_endpoint_flips_kayak_enabled`, `test_toggle_kayak_endpoint_returns_404_for_missing_tracker`) were explicitly flagged in the plan as "add during implementation (depend on 3.8's exact route/template shape)" — added to `tests/test_kayak_scheduling.py`, following the file's existing conventions (no new file, no modification of any existing test).
- No other new tests added; no test gaps found beyond what the plan already anticipated.

## Follow-ups / noted but not done

- **Live DB migration (3.1's `ALTER TABLE`)** — not run. Needs explicit user confirmation per project CLAUDE.md before Kayak can be enabled on any real tracker.
- `backend/scheduler.py::add_tracker_job` has a redundant local `from datetime import timedelta` (line ~151) that pre-dates this phase and is now shadowed by the module-level import added for the Kayak block. Harmless (no behavior change), out of scope for this phase's surgical-change rule — not touched.
- Phase 4 (`best_source` attribution + Source column) is unstarted; its 5 failing tests are pre-existing and untouched by this phase.

## Confidence rating

**Certain.** All Phase 3 tests pass for the intended reasons (verified against the pre-implementation failure baseline), full-suite non-regression confirmed, and the one open design question (job-stacking mitigation) was resolved by direct runtime inspection rather than assumption.
