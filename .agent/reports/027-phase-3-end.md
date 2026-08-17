# 027 Phase 3 — scheduler hygiene (#7 + #6)

**Date:** 2026-08-17
**Plan:** `.agent/plans/027-refactor-scan-remediation.md`, Phase 3 (#7 + #6)

## What I built

1. **#7 (field-drop trap):** `search_and_store`'s hand-spelled `prices` dict
   (11 named `FlightResult` fields + `flight_key`) is now
   `[{**asdict(r), "flight_key": make_flight_key(r)} for r in results]`.
   `insert_flight_prices` already reads columns via `p.get(...)`, so extra
   keys are ignored and the mapping is total by construction — a future
   `FlightResult` field can no longer be silently dropped.
2. **#6a (default trap):** removed `delay`'s `= True` default from
   `search_and_store`. The one call site that had actually been relying on
   it — `add_tracker_job`'s `scheduler.add_job(...)` registration — now
   passes `args=[tracker_id, True]` explicitly. All five other call sites
   (`api.py` x2, `pages.py` x3) already passed `delay=False` explicitly, so
   they needed no change.
3. **#6b (log dedup):** extracted `_log_source_error(event, source,
   tracker_id)` for the two identical `getattr(source, "last_error", ...) ->
   insert_log` blocks (the main `get_sources()` loop, event `search_error`;
   the Kayak call, event `kayak_search_error`). Verified the message text is
   unchanged: the Kayak block's original literal `f"KayakSource: {last_error}"`
   equals `f"{type(kayak_source).__name__}: {last_error}"` since `KayakSource`
   is the class's actual name, so the shared helper's `type(source).__name__`
   form reproduces both call sites' original messages exactly.

## Tests added

The plan named the required test ("a test asserting every `FlightResult`
field reaches the row dict") but, as in Phases 1 and 2, no test file existed
for it yet — written as part of this phase, in a new `tests/test_scheduler.py`
(no general, non-Kayak-specific scheduler test file existed; `test_kayak_scheduling.py`
is explicitly scoped to Kayak behavior per its own docstring):

- `test_every_flight_result_field_reaches_the_stored_row` — the plan's named
  test. Walks `dataclasses.fields(FlightResult)` rather than naming any
  field, so it covers a future field without being edited; builds one
  `FlightResult`, runs it through `search_and_store` with `get_sources()`
  mocked to return it and Kayak mocked to return nothing, then asserts every
  field's value made it into the stored row.
- `test_search_and_store_has_no_delay_default` — asserts the `delay`
  parameter has no default via `inspect.signature`. Discovery-gap addition
  (not named by the plan) covering #6a directly, flagged here per the
  skill's rule for tests added beyond the plan's explicit list.
  It would fail against pre-phase-3 code (default was `True`).
- `test_add_tracker_job_passes_delay_explicitly` — asserts
  `add_tracker_job`'s `scheduler.add_job` call includes `args=[1, True]`.
  Also a discovery-gap addition covering #6a's one real call site. Would
  fail against pre-phase-3 code (`args=[tracker_id]` only).

## Verification

Baseline (before any Phase 3 edit), full suite:
```
$ docker exec airfare-monitor python -m pytest tests/ -k "not slow"
====================== 517 passed, 3 deselected in 38.07s ======================
```

Post-refactor, before adding new tests (proves #6/#7's code changes broke
nothing already covered):
```
====================== 517 passed, 3 deselected in 38.07s ======================
```

New test file alone:
```
$ docker exec airfare-monitor python -m pytest tests/test_scheduler.py -v
tests/test_scheduler.py::test_every_flight_result_field_reaches_the_stored_row PASSED
tests/test_scheduler.py::test_search_and_store_has_no_delay_default PASSED
tests/test_scheduler.py::test_add_tracker_job_passes_delay_explicitly PASSED
============================== 3 passed in 0.36s ===============================
```

Full suite after adding the new tests:
```
$ docker exec airfare-monitor python -m pytest tests/ -k "not slow"
====================== 520 passed, 3 deselected in 40.61s ======================
```

(520 = 517 + 3 new tests; no test removed or modified.)

## Deviations from the plan

None in substance. As in Phases 1 and 2, the plan described the required
test but no test file existed for it — written this phase (see "Tests
added"). Two of the three tests in the new file (delay-default removal, and
`add_tracker_job`'s explicit `args`) are discovery-gap additions beyond the
plan's single named test, covering #6 directly rather than leaving it
unverified by an executable test — flagged per the skill's rule rather than
added silently.

## Follow-ups / noted, not done

None outside this phase's scope.

## Confidence

**certain** — mechanical, behavior-preserving changes; full suite green
before and after; the Kayak-message equivalence (`type(source).__name__` vs.
the original literal `"KayakSource"`) was checked explicitly rather than
assumed.

## Commit

See `git log` for the `[phase-3.1]`-tagged commit following this report.
