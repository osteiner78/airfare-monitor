# Phase 4 — Sidebar UI + client-side filter engine

## What was built

**Server (`backend/pages.py`):** `_build_detail_context` now computes `max_stops`
(max stops across current flights) and `max_duration` (max non-null `duration_min`,
default 0) and adds them to the returned context.

**Template (`detail_page.html`):** The `{% if latest_snapshot %}` block is wrapped in
`.detail-layout` (flex). A `.filter-sidebar` `<aside>` sits alongside `.detail-main`.
Sidebar contains:
- `<select id="filter-stops">`: "Any" + one option per 0..max_stops
- `<input type="range" id="filter-duration">`: min=0, max=max_duration, default=max_duration
- `<button id="filter-reset">`: Reset to defaults
- `filters.js` is included after `charts.js`.

**CSS (`app.css`):** Appended `.detail-layout`, `.detail-main`, `.filter-sidebar`,
`.filter-group`, `.filter-reset-btn`, `.row-filtered` (opacity 0.35, grey accent),
and a `@media (max-width: 768px)` stacking rule. No existing rules were touched.

**JS (`filters.js`):** IIFE. `applyFilters()` reads controls, filters `window.allFlights`
(stops ≤ maxStops; null duration always passes), sorts survivors by price asc, takes
`top_n`, assigns `CHART_COLORS` by rank, calls `window.renderPriceChart`, then iterates
`tr[data-flight-key]` rows: filtered → `.row-filtered`; survivor top-N → `--row-color`
+ `.row-colored`; else neutral. `init()` binds change/input/click listeners. Called
directly at script load and re-bound via `htmx:afterSwap`.

## Verification output

```
pytest tests/test_filters.py tests/test_pages.py -v

tests/test_filters.py::test_all_flights_includes_flight_beyond_top_n PASSED
tests/test_filters.py::test_chart_data_capped_at_top_n_while_all_flights_is_not PASSED
tests/test_filters.py::test_all_flights_entry_includes_stops_and_duration PASSED
tests/test_filters.py::test_all_flights_includes_full_history_series_per_flight PASSED
tests/test_filters.py::test_row_carries_data_stops_attribute PASSED
tests/test_filters.py::test_row_carries_data_duration_attribute PASSED
tests/test_filters.py::test_all_flights_is_empty_array_when_no_snapshot PASSED
tests/test_filters.py::test_row_with_null_duration_renders_empty_data_duration PASSED
tests/test_filters.py::test_detail_page_renders_filter_sidebar PASSED
tests/test_filters.py::test_duration_slider_max_equals_longest_flight PASSED
tests/test_filters.py::test_stops_select_max_option_equals_most_stops PASSED
tests/test_filters.py::test_sidebar_renders_with_single_flight PASSED
tests/test_filters.py::test_duration_slider_max_is_zero_when_all_durations_null PASSED
[all test_pages.py: 24 PASSED]

37 passed in 1.17s

pytest tests/ -v -k "not slow" → 145 passed, 1 deselected
```

## Manual smoke matrix

NOTE: Manual browser smoke was not performed during this automated implementation run.
The user should verify the following matrix against the running app:

1. Open a tracker with several flights → sidebar present; all rows colored/neutral as before.
2. Lower max-stops to Nonstop → 1-stop+ rows grey out; chart drops their lines; a previously
   uncharted nonstop flight gets promoted with a color; its row accent matches the new line.
3. Drag duration slider down → long flights grey; chart + colors recompute consistently.
4. Set both filters to exclude everything → chart shows "No price data yet"; all rows grey.
5. Reset → identical to initial server render (colors + lines).
6. Click "Search Now" → controls reset, chart redraws, filters re-applicable.

## Commit

`f3657a5` — [phase-4.1] sidebar UI + client-side filter engine (stops + duration)

## Deviations

None from plan intent. One minor addition: `window.chartTopN` is emitted in Phase 2
(alongside `allFlights`) rather than Phase 4, as it's part of the same data contract.

## Confidence

certain (server tests), needs-review (browser smoke not run in this session)
