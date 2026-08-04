# Plan 017 — Phase 1 & 2 amendment report

Implements the addendum tasks added to the plan after Phases 1 and 2 shipped
(commit `fb90c52`, "Add two gaps found auditing the shipped phases"): task
1.10 and tasks 2.12/2.13, plus the 4 fail-first tests written against them.

## What was built

**1.10 — `history_by_key` dedup (`backend/pages.py`).** The chart/history
series was appending one point per `get_price_history` row, so a flight
quoted by two sources in one snapshot drew two points at the same timestamp
(a vertical segment on the line). Fixed by merging points that share both
`flight_key` and the row's `snapshot_id`, keeping the cheaper price.

**Deviation from the addendum's literal suggestion:** the addendum's own
task text says to key the merge on `(flight_key, searched_at)`. Implementing
that literally (string-comparing the formatted timestamp) broke a pre-existing,
already-passing test — `test_filters.py::test_all_flights_includes_full_history_series_per_flight`
— which creates two *distinct* snapshots back-to-back and expects two
*separate* chart points even though SQLite's `datetime('now')` has only
second resolution and both snapshots can land in the same second. Keying on
the formatted timestamp string collapsed those two legitimately-different
snapshots into one point, which is wrong: this test isn't testing the
same-snapshot dual-source case the addendum was written for, it's testing
"the chart shows one point per *snapshot*, not per second." Switched the
merge key to `snapshot_id` instead — `get_price_history` (`backend/db.py`)
now also `SELECT`s `fp.snapshot_id` (no existing test asserts the exact set
of returned columns, so this is additive and safe) — which correctly merges
same-snapshot duplicates while keeping different-snapshot points separate
regardless of timestamp collision. This is more correct than the addendum's
literal instruction, not a smaller version of it: it fixes the exact defect
1.10 describes without introducing the second-resolution collision defect.

**2.12 — visible failure on validation drop (`backend/sources/kayak.py`,
`_search_inner`).** After `_validate`, if every extracted row was dropped,
`search()` now sets `last_error` (naming the drop count) and
`last_error_level = "WARNING"` before returning `[]`, so a fully-hallucinated
extraction is no longer indistinguishable from a clean "route has no
flights" success on `/monitor`. If only *some* rows were dropped, the run
still returns its (non-empty) results but also sets `last_error`/`WARNING`
naming how many of how many were dropped — extraction quality signal for the
reliability follow-up plan, without failing the run.

**2.13 — three cleanups in `backend/sources/kayak.py`, none behavioral on
the happy path:**
- `_map_result`: `stops=row.get("stops")` → `stops=row.get("stops") or 0`.
  Chose the "default to 0" option the addendum offered (over widening
  `FlightResult.stops`'s type) to keep `KayakSource` consistent with every
  other source, which already guarantees an `int`.
- `_wait_for_results_stable`: `asyncio.get_event_loop()` →
  `asyncio.get_running_loop()` (the addendum's exact suggestion — the former
  is deprecated when already inside a running coroutine on 3.12).
  `_OVERALL_TIMEOUT_S`: was a bare `90.0`, exactly equal to the worst-case
  render time alone (`page.goto`'s own 45s timeout plus
  `_wait_for_results_stable`'s separate 45s cap = 90s), leaving zero budget
  for the LLM call. Changed to a derived constant,
  `2 * _RENDER_TIMEOUT_S + _LLM_TIMEOUT_S + 30.0` (150s at current values) —
  chose "raise the overall cap" over "lower the render halves" since the
  render timeouts were sized against the hand prototype's real observed
  Kayak load times (per the plan's Phase 2 intent) and shrinking them risked
  cutting off a legitimately slow but successful render.

## Verification output

```
pytest tests/test_pages_multi_source.py tests/test_kayak_source.py -v -k "not slow"
============================= 60 passed, 1 deselected in 10.88s =======================
```
(includes the 4 new addendum tests: `test_chart_series_has_one_point_per_snapshot_for_a_dual_sourced_flight`,
`test_chart_series_point_uses_cheapest_price_for_a_dual_sourced_flight`,
`test_search_warns_when_validation_drops_every_row`,
`test_search_reports_dropped_row_count_when_some_rows_survive_validation`)

```
pytest tests/ -v -k "not slow"
================ 25 failed, 262 passed, 3 deselected in 26.30s =================
```
All 25 remaining failures are confined to `test_best_source.py` (6, Phase 4)
and `test_kayak_scheduling.py` (19, Phase 3 — including the `kayak_enabled`
schema column Phase 3.1 adds). 262 passed = the 258 baseline after Phase 2 +
4 newly-green addendum tests. No regressions — confirmed specifically for
`test_filters.py` (all 21 tests pass, including the one the literal
timestamp-keyed approach broke and the snapshot_id-keyed fix restores) and
`test_db.py` (21 passed, `get_price_history`'s new `snapshot_id` column
doesn't break its caller in `backend/api.py` or any test).

Also confirmed the live dev container (which auto-reloaded on each edit)
stayed healthy throughout and a real tracker's chart data still renders with
full point counts after the `history_by_key` rewrite.

## Commit hash(es)

See below — committed after this report, message
`[phase-1.10,2.12-2.13] amendment: chart point merge fix + Kayak failure visibility`.

## Deviations from the plan

- 1.10's merge key: `snapshot_id`, not the formatted `searched_at` string —
  see rationale above (the literal instruction broke a passing test; the
  `snapshot_id` key is the correct fix for the addendum's stated defect
  without the second-resolution collision side effect).

## Test gaps flagged / new tests added

None beyond what the amendment itself specified. All 4 addendum tests passed
as written; no gaps found.

## Follow-ups / noted-but-not-done

- Same two open items carried from the Phase 2 report: confirm the DeepSeek
  model ID (or switch to Claude Haiku 4.5) and Kayak's real currency URL
  param, both against live traffic, before Phase 6.

## Confidence rating

**Certain** for 2.12/2.13 (straightforward, exactly matches the addendum's
own specified fix). **Likely-good** for 1.10 — the deviation from the
addendum's literal wording was necessary and is more correct than the
literal instruction, but it's still a judgment call made without the
orchestrator's sign-off; flagging it explicitly here rather than silently
diverging.
