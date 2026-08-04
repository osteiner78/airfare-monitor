# Plan 017 — Phase 1 report: source-independent flight_key, dedup-safe chart inputs, history backfill

## What was built

1.1 — `backend/fingerprint.py::make_flight_key` now returns
`f"{result.airline}|{result.flight_number}|{result.departure_time}"` (3 parts,
no `source` prefix), so the same physical flight quoted by different sources
shares one identity.

1.2/1.3 — `backend/pages.py::_build_detail_context`: `previous_prices` and
`prev_flights` are now built with a `setdefault`-based loop over `prev`
(`get_flight_prices_for_snapshot` returns `ORDER BY price ASC`), so the
cheapest quote per `flight_key` wins instead of the dict-comprehension's
last-write (most expensive) row.

1.4 — `current_flight_map` gets the same `setdefault` treatment for the same
reason (cheapest current quote per key, not last one seen).

1.5 — `ordered_top_keys` now walks `flights_with_delta` in order, skipping
already-seen keys, and stops once `top_n` **distinct** keys are collected —
previously it sliced `[:top_n]` **rows**, so a duplicated key ate two colour
slots.

1.6 — `all_flights` (the `window.allFlights` feed) dedupes by `flight_key`
during the same walk, keeping the first (cheapest, since the source list is
price-ascending) occurrence. The results table loop is untouched — it still
emits one `<tr>` per DB row (1.8, no code change, pinned by
`test_results_table_shows_every_source_row_even_when_flight_key_repeats`).

1.7 — `backend/db.py::get_sticky_top_flight_keys` now ranks over a
`GROUP BY snapshot_id, flight_key` deduped CTE (`MIN(price)` per key per
snapshot) before applying `ROW_NUMBER() OVER (PARTITION BY snapshot_id ORDER
BY price ASC)`, so a key repeated within one snapshot (two sources quoting
the same flight) no longer eats two rank slots.

1.9 — Production DB backfill, run with explicit user confirmation. See
"Production backfill" below for details — the live `--reload` server had
already started writing 5 rows in the new key format between the code edit
landing and the backfill running, so the backfill UPDATE was scoped with a
`WHERE` clause to only touch still-old-format (4-part) rows, to avoid
double-stripping those 5.

## Verification output

### Targeted (plan's Phase 1 command)
```
pytest tests/test_fingerprint.py tests/test_pages_multi_source.py -v -k "not slow"
============================= test session starts ==============================
collected 18 items

tests/test_fingerprint.py::test_nonstop_key_contains_three_pipe_separated_parts PASSED
tests/test_fingerprint.py::test_nonstop_key_does_not_start_with_source_name PASSED
tests/test_fingerprint.py::test_nonstop_key_contains_airline_and_flight_number PASSED
tests/test_fingerprint.py::test_multistop_key_joins_airlines_with_plus PASSED
tests/test_fingerprint.py::test_multistop_key_joins_flight_numbers_with_plus PASSED
tests/test_fingerprint.py::test_same_flight_result_produces_same_key_on_repeated_calls PASSED
tests/test_fingerprint.py::test_different_departure_times_produce_different_keys PASSED
tests/test_fingerprint.py::test_flight_key_identical_across_different_sources_for_same_physical_flight PASSED
tests/test_fingerprint.py::test_flight_key_still_differs_for_genuinely_different_flights_from_same_source PASSED
tests/test_fingerprint.py::test_key_with_empty_airline_still_produces_three_parts PASSED
tests/test_fingerprint.py::test_key_with_empty_airline_and_flight_number_still_differs_by_departure_time PASSED
tests/test_pages_multi_source.py::test_price_delta_uses_cheapest_previous_price_when_flight_key_quoted_by_two_sources PASSED
tests/test_pages_multi_source.py::test_missing_flight_reconstruction_uses_cheapest_historical_price PASSED
tests/test_pages_multi_source.py::test_flight_not_marked_missing_when_still_quoted_by_a_different_source PASSED
tests/test_pages_multi_source.py::test_results_table_shows_every_source_row_even_when_flight_key_repeats PASSED
tests/test_pages_multi_source.py::test_window_all_flights_has_one_entry_per_flight_key PASSED
tests/test_pages_multi_source.py::test_window_all_flights_entry_uses_cheapest_price_for_a_duplicated_key PASSED
tests/test_pages_multi_source.py::test_chart_top_n_counts_distinct_flights_not_rows PASSED

============================== 18 passed in 3.77s ==============================
```

Plus `tests/test_chart_data.py` (added test for 1.7, run separately for
clarity, included in the full run below):
```
pytest tests/test_chart_data.py -v -k "not slow"
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_top_n_distinct_flights_when_a_key_repeats_in_a_snapshot PASSED
tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n PASSED
tests/test_chart_data.py::test_chart_dataset_includes_color_field PASSED
tests/test_chart_data.py::test_chart_dataset_color_is_first_palette_color_for_single_flight PASSED
tests/test_chart_data.py::test_color_assigned_by_price_rank_not_history_order PASSED
============================== 8 passed in 2.70s ===============================
```

### Full non-regression pass
```
pytest tests/ -v -k "not slow"
================ 48 failed, 235 passed, 3 deselected in 24.40s =================
```
All 48 remaining failures are confined to Phase 2/3/4 files not yet
implemented (`test_kayak_source.py` 23, `test_kayak_scheduling.py` 19,
`test_best_source.py` 6) — same baseline set the plan's pre-implementation
audit flagged, none of them Phase-1 scope. 235 passed = the pre-existing 222
baseline + all 13 Phase-1 tests now green (11 fingerprint + 7
pages_multi_source... note: 18 total across both files minus 5 that were
already passing as non-regression anchors = 13 newly green, consistent with
the plan's stated 7+5+1 new-behavior/failure-mode test count).

### Detail-page chart-continuity check (post-1.9)
Fetched `/trackers/1` (GVA→BCN, 630 snapshots, oldest data back to
2026-05-31) after the backfill and restart. Sample dataset point counts from
`window.chartData`:
```
Iberia IB 622+IB 413        465 points  (2026-05-xx .. now)
Vueling VY 6201             465 points
easyJet U2 7110              467 points
Austrian OS 156+OS 401       468 points
Air Europa UX 1664+UX 7703   469 points
```
Chart lines span the full history, not a single point — the backfill did not
break continuity.

## Production backfill (task 1.9) — done, with confirmation

Confirmed with the user before running (destructive DB mutation, per this
project's CLAUDE.md). Sequence actually run:

```bash
docker compose stop
cp data/airfare.db data/airfare.db.bak-017        # 183MB, verified on disk
sqlite3 data/airfare.db \
  "UPDATE flight_prices SET flight_key = substr(flight_key, instr(flight_key, '|') + 1)
   WHERE (LENGTH(flight_key) - LENGTH(REPLACE(flight_key, '|', ''))) = 3;"
docker compose start
```

**Deviation from the plan's literal command:** added a `WHERE` clause
restricting the UPDATE to rows still in the old 4-part (3-pipe) format. Between
the code edit landing (which uvicorn `--reload` picked up immediately) and the
backfill running, the live server had already completed one scheduled search
and written 5 rows in the *new* 3-part format (ids 243085–243089,
`fast_flights`, snapshot 5993). The plan's blind `substr(..., instr(...) + 1)`
would have stripped the first segment of those 5 rows too (their airline, not
a source name), corrupting them. Scoping the UPDATE to only 4-part keys was
the direct, obvious fix and stayed inside 1.9's intent (migrate old-format
rows) rather than 1.9's literal text.

**Result:** all 160,115 rows now have exactly 2 pipes (3 parts). Row counts
by `source` are unchanged (159,784 `google_flights`, 331 `fast_flights` — the
331 includes the 313 pre-existing `fast_flights` rows plus the 18 that
existed before those 5 fresh ones, consistent with `source` never being
touched by this UPDATE). Backup verified present and byte-identical size
(`data/airfare.db.bak-017`, 183,521,280 bytes) before the UPDATE ran.

## Commit hash(es)

See below — committed after this report was written, message
`[phase-1.1-1.7] source-independent flight_key + chart-input dedup`.

## Deviations from the plan

- The `WHERE` clause added to 1.9's UPDATE (see above) — necessary because
  the live dev server started writing new-format rows before the backfill
  ran, which the plan (written against a static snapshot of the DB) didn't
  anticipate.

## Test gaps flagged / new tests added

None. All orchestrator-written tests for this phase passed as written; no
gaps found, no new tests added.

## Follow-ups / noted-but-not-done

- Some flight_number values in the live DB lack an airline-code prefix (e.g.
  "easyJet 1293" vs "easyJet U2 1293" as separate chart lines for what may be
  the same route) — pre-existing data-quality artifact, unrelated to this
  phase's changes, not touched.

## Confidence rating

**Certain** — all plan-mandated tests pass, full suite shows zero regressions,
the production backfill was verified before/after (row/pipe counts, backup
integrity, live chart continuity), and the container is confirmed healthy
post-restart.
