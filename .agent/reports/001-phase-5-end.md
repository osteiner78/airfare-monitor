# 001 Phase 5 — End Report

## What was built

- **Task 5.1**: `frontend/templates/tracker.html` — Detail page with route header, chart container, results table, Search Now button, and pause/resume/delete controls. Shows empty state when no snapshots exist.
- **Task 5.2**: `frontend/static/charts.js` — Chart.js line chart from embedded JSON data. One line per flight key, time-based X-axis, hover tooltips.
- **Task 5.3**: `frontend/templates/partials/results_table.html` — Table of current flights sorted by price with columns for airline, flight number, departure, arrival, duration, stops, price, and delta.
- **Task 5.4**: `frontend/templates/partials/price_badge.html` — Color-coded span: green ↓ for price drop, red ↑ for increase, blue "new" for first-time flights.
- **Task 5.5**: Search Now button — HTMX POST to `/trackers/{id}/search` (pages route), triggers `search_and_store()`, swaps entire detail content with updated data.
- **Task 5.6**: Pause/resume uses `/trackers/{id}/toggle-detail` (re-renders full tracker.html). Delete uses `/trackers/{id}/detail` which adds `HX-Redirect: /` header.
- **DB addition**: `get_flight_prices_for_snapshot(snapshot_id)` — fetches all flight_prices rows for a snapshot, ordered by price.
- **Pages additions**: `GET /trackers/{id}`, `POST /trackers/{id}/search`, `PATCH /trackers/{id}/toggle-detail`, `DELETE /trackers/{id}/detail`. Shared context builder `_build_detail_context()` computes deltas by comparing current vs previous snapshot flight prices.

## Verification output

Regression test suite: **52 passed, 2 expected failures** (Phase 6), unchanged.

```
================== 2 failed, 52 passed, 1 deselected in 1.01s ==================
```

Smoke test:

```
=== Create tracker ===
201 Created
=== Detail page status ===
200
=== Detail page content check ===
Has GVA: True
Has BCN: True
Has date: True
Has chart.js CDN: True
Has Search Now: True
Has Pause: True
Has Delete: True
Has empty state: True
=== History endpoint ===
flights: 0 best_prices: 0
=== Search Now ===
200
```

## Deviations from plan

- **Separate toggle-detail and delete-detail routes**: The dashboard's toggle returns a card partial (`outerHTML` swap), while the detail page needs a full page re-render. Added `/trackers/{id}/toggle-detail` (PATCH) and `/trackers/{id}/detail` (DELETE with `HX-Redirect`) to handle detail page context without breaking dashboard behavior.

## Test gaps

None. Phase 5 has no orchestrator-written tests.

## Follow-ups

- The dashboard delete currently returns full `dashboard.html` into `#tracker-list` via `innerHTML` swap — technically embeds a full HTML page inside a div. Phase 6 polish should extract a `tracker_list.html` partial.
- Chart.js uses a CDN (`jsdelivr`). Phase 6 could bundle it locally for offline use.
- The search-now spinner needs network requests; emoji fallback omitted per convention.
- The date column in results_table shows raw ISO timestamps — Phase 6 could format these.

## Confidence

**certain** — all smoke checks pass, regression suite unchanged, detail page renders with all required elements.
