# Phase 1 — Deterministic price-rank color order

## What was built

Replaced the `latest_top_keys` set and history-first-seen `chart_datasets` dict in
`_build_detail_context` with an `ordered_top_keys` list derived from
`flights_with_delta[:top_n]` (price ascending). Pre-created `chart_datasets` entries
in that price-rank order, then filled data points from history in a separate pass.
Colors are assigned before history is iterated so position 0 always maps to the
cheapest current flight.

## Verification output

```
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker PASSED
tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n PASSED
tests/test_chart_data.py::test_chart_dataset_includes_color_field PASSED
tests/test_chart_data.py::test_chart_dataset_color_is_first_palette_color_for_single_flight PASSED
tests/test_chart_data.py::test_color_assigned_by_price_rank_not_history_order PASSED
tests/test_chart_colors.py::test_single_key_gets_first_palette_color PASSED
tests/test_chart_colors.py::test_distinct_colors_for_keys_within_palette_size PASSED
tests/test_chart_colors.py::test_assigns_colors_in_positional_order PASSED
tests/test_chart_colors.py::test_handles_unicode_and_pipe_delimited_keys PASSED
tests/test_chart_colors.py::test_returns_empty_dict_for_empty_key_list PASSED
tests/test_chart_colors.py::test_palette_cycles_when_more_keys_than_colors PASSED
tests/test_chart_colors.py::test_eleventh_key_reuses_first_color PASSED
tests/test_chart_colors.py::test_duplicate_keys_collapse_to_single_entry PASSED
tests/test_pages.py::test_charted_row_carries_its_chart_color PASSED
[... 24 more pages tests passing ...]

39 passed in 0.87s
```

## Commit

`3ab14c0` — [phase-1.1] deterministic price-rank color order in chart datasets

## Deviations

None. Straightforward replacement; label derivation moved from history row to current
flight data, which is cleaner and has the same fallback chain.

## Follow-ups

None.

## Confidence

certain
