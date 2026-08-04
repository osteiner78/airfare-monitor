# 017 Phase 4 — End Report

## What was built

- **4.1** `backend/db.py` `get_tracker_summaries`: added a `best_source` correlated subquery immediately after `best_flight_number`, same shape (latest snapshot, `fp.tracker_id = t.id`), ordered `fp.price ASC, fp.source ASC LIMIT 1`. The `source ASC` tiebreak makes attribution deterministic when two sources quote the identical price for the same flight in the same snapshot — expected now that sources share a snapshot, not an edge case.
- **4.2** `backend/pages.py`: added a `_SOURCE_LABELS` dict and `source_label` Jinja filter, registered alongside `currency_symbol`/`airline_code`: `"google_flights"` → `"Google Flights"`, `"fast_flights"` → `"Google Flights (alt)"`, `"kayak"` → `"Kayak"`, unknown values fall back to the raw string via `dict.get(s, s)`.
- **4.3** `frontend/templates/partials/results_table.html`: added `<th>Source</th>` and `<td>{{ item.flight.source | source_label }}</td>`. Templating only — `item.flight` already carried `source`.
- **4.4** Confirmed (no code change): `prev_flights` (fixed in Phase 1) does `missing = dict(prev_flight)`, copying the full original row including `source`, so reconstructed "missing" rows render a source label too. Verified by the passing `test_results_table_shows_source_for_each_flight_row`, which includes a row transitioning through the missing path implicitly via the shared code path — confirmed directly by reading `backend/pages.py:374-379`.

## Verification output

```
$ docker exec airfare-monitor python -m pytest tests/test_best_source.py -v -k "not slow"
collected 6 items

tests/test_best_source.py::test_get_tracker_summaries_best_source_matches_cheapest_price_row PASSED
tests/test_best_source.py::test_get_tracker_summaries_best_source_updates_when_a_cheaper_source_appears PASSED
tests/test_best_source.py::test_get_tracker_summaries_best_source_is_none_when_no_snapshots PASSED
tests/test_best_source.py::test_best_source_is_deterministic_when_two_sources_tie_on_price PASSED
tests/test_best_source.py::test_results_table_shows_source_for_each_flight_row PASSED
tests/test_best_source.py::test_results_table_source_label_falls_back_to_raw_value_for_unknown_source PASSED

6 passed in 2.32s
```

```
$ docker exec airfare-monitor python -m pytest tests/ -v -k "not slow"
...
289 passed, 3 deselected in 24.93s
```

Full output confirmed no pre-existing test broken; the only test file with new activity was `test_best_source.py` (all 6 passing, up from 5 failed/1 passed before this phase's edits).

## Commit

`1b6dd36` — `[phase-4.1-4.4] Add best_source attribution and Source column`

## Deviations from the plan

None. Diff matched the plan's "Files" list exactly: `backend/db.py`, `backend/pages.py`, `frontend/templates/partials/results_table.html` (plus `CLAUDE.md` per the implement skill's finalization step). `get_sticky_top_flight_keys` / `get_best_price_series` were left untouched, per the plan's explicit "What NOT to touch."

## Pre-flight note (the caveat attached to this task)

The task arguments flagged that "perf work touches `get_sticky_top_flight_keys`, which Phase 1.7 also modifies... the implementer will be editing a function whose current shape isn't on main yet." Checked before starting: Phase 1 (including 1.7) is already committed on this branch (`6c11607 [phase-1.1-1.7] source-independent flight_key + dedup-safe chart inputs`, confirmed via `git log`), so `get_sticky_top_flight_keys`'s current shape (the `ROW_NUMBER()` per-snapshot-deduped rewrite) is already on `017-kayak-source`. Separately, Phase 4's own scope (per the plan text) explicitly excludes `get_sticky_top_flight_keys` — "chart data feed is unaffected; source attribution is a summary/detail concern here." No "perf work" touching that function appears anywhere in Phase 4's tasks. The caveat doesn't describe this phase as written; flagging it here rather than silently acting on a scope note that didn't match the plan.

## Test gaps / new tests

None. All required tests were pre-written and none needed modification.

## Follow-ups (noted, not done — out of scope for this phase)

- The `fast_flights` → `"Google Flights (alt)"` label was an open question in the plan (4.2); picked because `fast_flights.py` scrapes the same Google Flights inventory via a different mechanism (public search-results URL vs. fli's batchexecute RPC). Revisit if that reads confusingly in the UI.

## Confidence

**certain** — small, contained diff (18 lines across 3 code files), every plan task has a corresponding passing test, full suite green, no scope creep.
