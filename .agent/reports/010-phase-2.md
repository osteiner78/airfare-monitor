# Phase 2 — Full per-flight data contract

## What was built

- `_build_detail_context` now builds `history_by_key` (a dict from flight_key → [{x,y}...])
  and uses it for both `chart_datasets` data fill and a new `all_flights` list.
- `all_flights` covers every current non-missing flight (not just top-N) with
  `{flight_key, label, price, stops, duration_min, data}`.
- `detail_page.html` emits `window.allFlights` and `window.chartTopN` next to `window.chartData`.
- `results_table.html` `<tr>` rows now carry `data-stops` and `data-duration` attributes
  (empty string when `duration_min` is null).

## Verification output

```
tests/test_filters.py::test_all_flights_includes_flight_beyond_top_n PASSED
tests/test_filters.py::test_chart_data_capped_at_top_n_while_all_flights_is_not PASSED
tests/test_filters.py::test_all_flights_entry_includes_stops_and_duration PASSED
tests/test_filters.py::test_all_flights_includes_full_history_series_per_flight PASSED
tests/test_filters.py::test_row_carries_data_stops_attribute PASSED
tests/test_filters.py::test_row_carries_data_duration_attribute PASSED
tests/test_filters.py::test_all_flights_is_empty_array_when_no_snapshot PASSED
tests/test_filters.py::test_row_with_null_duration_renders_empty_data_duration PASSED
tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n PASSED
tests/test_pages.py::test_detail_page_contains_results_table_when_snapshot_exists PASSED
[5 Phase 4 sidebar tests still failing — expected at this stage]

140 passed, 5 failed (Phase 4 only), 1 deselected
```

## Commit

`deeeeca` — [phase-2.1] ship window.allFlights + data-stops/data-duration per row

## Deviations

None.

## Confidence

certain
