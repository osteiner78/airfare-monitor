# 005 — Start Report

## Scope

Four phases: add time adapter CDN + top-N DB query, refactor server-side chart data (sticky top-N filter, short labels), rewrite client-side charts.js (time scale, legend below, no animation), optional numeric axis fallback.

## Tests to turn green

- 3 in Phase 1: `test_chart_data.py` — `get_sticky_top_flight_keys` (ImportError → pass)
- 1 in Phase 2: `test_chart_datasets_limited_to_sticky_top_n` ("VY 6201" label → pass)

## Pre-work observations

- The `chartjs-adapter-date-fns` CDN is missing from `detail_page.html` (was in deleted `detail_content.html`).
- Adapter must load BEFORE Chart.js.
- `flight_key` format: `source|codes|numbers|departure_iso`. Index 1 = airline codes (e.g., "VY", "A3+A3").
- SQLite supports ROW_NUMBER since 3.25.0 — should work with aiosqlite.
