# 003 — Start Report

## Scope

Ten UX corrections on top of plans 001 and 002. No new tests — verification is via the existing test suite (non-regression) plus manual smoke test.

## Fixes expected to deliver

| # | Fix | Key file |
|---|-----|----------|
| 1 | Uppercase form POST codes | `backend/pages.py` |
| 2 | Pause updates detail header | `tracker.html`, `detail_page.html`, `pages.py` |
| 3 | Chart date format (ISO 8601) | `backend/pages.py` |
| 4 | Wider detail container (960px) | `app.css`, `tracker.html` |
| 5 | Airline name column from fli | `google_flights.py`, `results_table.html` |
| 6 | Arrival date column | `results_table.html` |
| 7 | Search Now button at top | `tracker.html`, `detail_content.html` |
| 8 | Card layout restructure | `tracker_card.html`, `app.css` |
| 9 | Booking URL from Google Flights | `google_flights.py` |
| 10 | Timezone offset preservation | `pages.py`, `results_table.html` |

## Pre-work observations

- f li provides `primary_airline_name` and `booking_token` on its result objects.
- `_build_detail_context` already splits ISO timestamps into date+time — just needs timezone offset in time display.
- The plan says Fix 2 needs a new `detail_page.html` partial that wraps header + `detail_content.html`.
- No test file in this plan — non-regression only.
