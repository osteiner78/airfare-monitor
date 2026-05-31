# 001 Phase 5 — Start Report

## Scope

Phase 5 builds the tracker detail page: `GET /trackers/{id}` shows a Chart.js price history chart, a results table with delta badges, and a "Search Now" button. Pause/resume and delete also work from this page.

## Tasks

| # | Task | Files |
|---|------|-------|
| 5.1 | Create `tracker.html` | `frontend/templates/tracker.html` |
| 5.2 | Create `charts.js` | `frontend/static/charts.js` |
| 5.3 | Create `results_table.html` partial | `frontend/templates/partials/results_table.html` |
| 5.4 | Create `price_badge.html` partial | `frontend/templates/partials/price_badge.html` |
| 5.5 | Wire HTMX: search now | `frontend/templates/tracker.html` |
| 5.6 | Wire HTMX: pause/resume/delete | `frontend/templates/tracker.html` |
| — | Add `GET /trackers/{id}` route to pages.py | `backend/pages.py` |
| — | Add `POST /trackers/{id}/search` route to pages.py | `backend/pages.py` |
| — | Add `get_flight_prices_for_snapshot()` to db.py | `backend/db.py` |

## Tests

Phase 5 has no orchestrator-written tests. Verification is via the plan's HTTP checks and manual smoke test.

## Pre-work observations

- Need a new DB function to fetch flight prices for a specific snapshot (not currently exposed).
- Price deltas are computed by comparing flight_keys between the latest and previous snapshots.
- Chart.js CDN will be added to tracker.html (not base.html, since only the detail page needs it).
- The "Search Now" HTMX flow: a pages.py route triggers `search_and_store()`, then returns updated HTML for the detail content.
- Delete redirects to dashboard via `HX-Redirect` response header.
