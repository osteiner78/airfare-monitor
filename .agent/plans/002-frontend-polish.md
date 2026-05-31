# 002 — Frontend Polish + Notification Log

## What this fixes

Phase 1–6 built a working airfare monitor, but several frontend bugs and UX gaps remain:
- Chart is blank (missing Chart.js time scale adapter)
- Pause on detail page duplicates the header/content
- "Change" column always blank (delta logic only fires on price movement, not on equality or new flights when prices match across snapshots)
- Results table overflows its container
- No feedback when airport codes are lowercase (search silently returns 0 results)
- `_evaluate_notifications` runs but never records output — no way to see if alerts triggered
- No "Refresh All" on dashboard
- Dates are raw ISO 8601 with no relative-time formatting
- No booking URL column in results table

---

## Phase 1 — Refactor HTMX Response Architecture

**Vertical slice**: Detail page HTMX actions (pause/resume, search-now) no longer embed a full HTML page inside a div. The pause duplication bug is fixed structurally.

### Tasks

| # | Task | Files |
|---|------|-------|
| 1.1 | Create `partials/detail_content.html` — contains `#detail-content` div (chart section, results section, search button) + chart script tags. No `<html>`, no `<head>`, no `detail-header` | `frontend/templates/partials/detail_content.html` |
| 1.2 | Update `tracker.html` to `{% include "partials/detail_content.html" %}` instead of inline content | `frontend/templates/tracker.html` |
| 1.3 | Change `POST /trackers/{id}/search` (pages route) to return `detail_content.html` partial | `backend/pages.py` |
| 1.4 | Change `PATCH /trackers/{id}/toggle-detail` to return `detail_content.html` partial | `backend/pages.py` |
| 1.5 | Change pause button `hx-target` on detail page to `#detail-content` (now inside the partial, so no outer duplication) | `frontend/templates/tracker.html` |

### Key design decisions

- `detail_content.html` is a standalone partial — it does NOT extend `base.html`. It includes chart scripts directly.
- The `detail-header` (back link, title, badge, pause/delete buttons) stays in `tracker.html` outside the partial — it is never re-rendered by HTMX swaps.
- `_build_detail_context` remains unchanged in this phase — it's still called to populate context for both routes.

### What NOT to touch

- `frontend/templates/partials/results_table.html`
- `frontend/templates/partials/price_badge.html`
- `backend/db.py`
- `backend/scheduler.py`
- `backend/api.py`

### Tests

New file: `tests/test_pages.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_dashboard_returns_200` | Fails — no pages tests exist yet |
| NEW-BEHAVIOR | `test_detail_page_returns_200_for_valid_tracker` | Fails |
| NEW-BEHAVIOR | `test_detail_page_returns_404_for_missing_tracker` | Fails |
| NEW-BEHAVIOR | `test_toggle_returns_card_partial` | Fails |
| NEW-BEHAVIOR | `test_search_now_returns_200` | Fails |
| NEW-BEHAVIOR | `test_add_tracker_returns_html_with_card` | Fails |
| FAILURE-MODE | `test_search_now_returns_404_for_missing_tracker` | Fails |
| FAILURE-MODE | `test_toggle_returns_404_for_missing_tracker` | Fails |

Note: `client` fixture already mocks `search_and_store`, so no real searches fire. Pages tests use the same `client` fixture from `conftest.py`.

### Verification

```bash
pytest tests/test_pages.py -v
# all 8 tests must pass

pytest tests/ -v -k "not slow"
# full regression: all 62 tests pass
```

---

## Phase 2 — Fix Chart + Table Layout

**Vertical slice**: Chart renders data lines. Results table fits its container. ISO timestamps split into date + time.

### Tasks

| # | Task | Files |
|---|------|-------|
| 2.1 | Add `chartjs-adapter-date-fns` CDN before Chart.js in detail templates | `frontend/templates/partials/detail_content.html`, `frontend/templates/tracker.html` |
| 2.2 | Remove `white-space: nowrap` from `.results-table th, .results-table td`. Add `overflow-x: auto` to `.results-section` unconditionally (not just mobile) | `frontend/static/app.css` |
| 2.3 | Split departure/arrival columns into Date + Time columns in results table. Extract date and time from ISO 8601 server-side | `frontend/templates/partials/results_table.html`, `backend/pages.py` |
| 2.4 | Add booking URL link column to results table. Render empty if `booking_url` is blank | `frontend/templates/partials/results_table.html` |

### Key design decisions

- ISO timestamp splitting: done in Python (`_build_detail_context`) — split `2026-09-15T09:45:00` into `2026-09-15` and `09:45`. Simpler than JS formatting.
- Chart.js time adapter: `chartjs-adapter-date-fns` is the official maintained adapter for Chart.js 4.x. Loaded from jsdelivr CDN.
- Booking URL: if fli returns a non-empty `booking_url`, render as `target="_blank"` link with text "Book". Otherwise show empty cell.

### What NOT to touch

- `frontend/static/charts.js` (already correct, just needs adapter loaded)
- `backend/scheduler.py`
- `backend/db.py`
- `backend/api.py`

### Tests

New file: `tests/test_pages.py` — add to existing (created in Phase 1)

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_detail_page_contains_booking_url_column` | Fails |
| NEW-BEHAVIOR | `test_detail_page_splits_departure_into_date_and_time` | Fails |
| NON-REGRESSION | `test_api_list_trackers_unchanged` | Passes now (pins existing API behavior) |

### Verification

```bash
pytest tests/test_pages.py -v
# Phase 1 + Phase 2 tests: all pass

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Phase 3 — Delta Logic + Change Column

**Vertical slice**: "Change" column shows meaningful badges: price down/up, no change (same price), new flight. Dashboard card delta uses same logic.

### Tasks

| # | Task | Files |
|---|------|-------|
| 3.1 | Modify `_build_detail_context` delta computation: when `prev_price` exists and equals current, set `delta = {"type": "same"}`. When no previous, set `delta = {"type": "new"}` (already done). Keep existing down/up logic | `backend/pages.py` |
| 3.2 | Add "same" badge rendering to `price_badge.html` (grey, showing price — e.g. `33.00 EUR`) | `frontend/templates/partials/price_badge.html` |
| 3.3 | Add `.price-badge.same` CSS | `frontend/static/app.css` |
| 3.4 | Modify `_enrich_summaries` delta computation: add `{"type": "same"}` when `best == prev` | `backend/pages.py` |
| 3.5 | Add "no change" display to `tracker_card.html` when delta type is "same" | `frontend/templates/partials/tracker_card.html` |

### Key design decisions

- "Same" badge shows the current price in grey — gives user confidence the system checked and found no change, vs the current blank cell which looks like a bug.
- Dashboard card delta: shows "no change" in grey text instead of blank.

### What NOT to touch

- `backend/db.py`
- `backend/scheduler.py`
- `backend/api.py`
- Chart-related files

### Tests

New file: `tests/test_delta.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_delta_same_when_prices_equal` | Fails — delta logic not yet updated |
| NEW-BEHAVIOR | `test_delta_new_when_no_previous_snapshot` | Passes (already correct) |
| NEW-BEHAVIOR | `test_delta_down_when_price_decreased` | Passes (already correct) |
| NEW-BEHAVIOR | `test_delta_up_when_price_increased` | Passes (already correct) |
| FAILURE-MODE | `test_delta_none_when_best_price_is_none` | Passes (already correct) |

### Verification

```bash
pytest tests/test_delta.py -v
# test_delta_same_when_prices_equal fails (target), rest pass

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Phase 4 — Input Normalization + Date Formatting

**Vertical slice**: Airport codes auto-uppercased. Dashboard shows clearer date labels. Relative time for "last checked".

### Tasks

| # | Task | Files |
|---|------|-------|
| 4.1 | Add `field_validator` to `TrackerCreate.origin` and `TrackerCreate.destination` that calls `.upper()` | `backend/models.py` |
| 4.2 | On tracker_card.html: add "Flight date:" label before `depart_date`, add "Last check:" label before last_searched_at | `frontend/templates/partials/tracker_card.html` |
| 4.3 | On tracker.html detail-header: add "Flight date:" label before `depart_date` | `frontend/templates/tracker.html` |
| 4.4 | Add JS-based relative time display for `last_searched_at`. Replace raw ISO with "2h ago" / "3d ago" format that updates on hover/title | `frontend/templates/base.html` (snippet) or new JS file |
| 4.5 | Style the date labels and relative time | `frontend/static/app.css` |

### Key design decisions

- Uppercase normalization via Pydantic validator — clean, single point of change. Does not affect tests (tests already use uppercase).
- Relative time: small JS function attached to existing `<span class="last-checked">`. Uses `title` attribute for raw timestamp. Updates on page load only (no live ticking — avoids complexity).
- Date labels use `font-size: 0.75rem; color: #888` to distinguish from values.

### What NOT to touch

- `backend/db.py`
- `backend/scheduler.py`
- `backend/api.py`

### Tests

New file: `tests/test_normalization.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_origin_is_uppercased_on_create` | Fails — no validator yet |
| NEW-BEHAVIOR | `test_destination_is_uppercased_on_create` | Fails |
| NEW-BEHAVIOR | `test_origin_preserves_uppercase` | Passes now |
| FAILURE-MODE | `test_depart_date_validation_still_works` | Passes now |

### Verification

```bash
pytest tests/test_normalization.py -v
# 2 NEW-BEHAVIOR fail, 2 pass (NON-REGRESSION + FAILURE-MODE)

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Phase 5 — Notification Log + Alert Badges

**Vertical slice**: When a notification rule triggers, it's recorded in a new `notification_log` table. Dashboard cards show an alert count badge.

### Tasks

| # | Task | Files |
|---|------|-------|
| 5.1 | Add `notification_log` table to schema (`id`, `notification_id`, `tracker_id`, `triggered_at`, `best_price`) | `backend/db.py` |
| 5.2 | Add `insert_notification_log()` DB function | `backend/db.py` |
| 5.3 | Add `get_recent_alerts_count()` DB function — count of alerts for a tracker in the last 24h | `backend/db.py` |
| 5.4 | Modify `_evaluate_notifications()` to call `insert_notification_log()` when a rule is triggered | `backend/scheduler.py` |
| 5.5 | Add alert count to `get_tracker_summaries()` query result | `backend/db.py` |
| 5.6 | Render alert count badge on tracker card (orange badge with number) | `frontend/templates/partials/tracker_card.html` |
| 5.7 | Add `.alert-count` badge CSS | `frontend/static/app.css` |
| 5.8 | Add `get_alert_count()` API helper to pages — compute alerts for each summary | `backend/pages.py` |

### Key design decisions

- `notification_log` is a standalone log table — does NOT foreign-key to `notifications` (rules can be deleted, but the log of past triggers should survive). Instead stores `notification_id` as a nullable int.
- Alert count badge shows number of alerts in last 24h. If 0, no badge shown (clean dashboard).
- `_evaluate_notifications` currently loops through rules and has empty if-bodies. The new code inserts a row for each triggered rule.

### What NOT to touch

- `backend/api.py` (no new API endpoints for notification_log in this phase)
- `frontend/templates/tracker.html` detail page
- Chart-related files

### Tests

New file: `tests/test_notification_log.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_notification_log_table_exists_after_init` | Fails — table not yet in schema |
| NEW-BEHAVIOR | `test_insert_notification_log_returns_dict_with_id` | Fails |
| NEW-BEHAVIOR | `test_get_recent_alerts_returns_zero_for_tracker_with_no_alerts` | Fails |
| NEW-BEHAVIOR | `test_evaluate_notifications_inserts_log_when_price_below_threshold` | Fails |
| FAILURE-MODE | `test_insert_notification_log_with_zero_price` | Fails |
| FAILURE-MODE | `test_get_recent_alerts_returns_zero_for_nonexistent_tracker` | Fails |

### Verification

```bash
pytest tests/test_notification_log.py -v
# all NEW-BEHAVIOR + FAILURE-MODE must FAIL before implementation

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Phase 6 — Refresh All + Polish

**Vertical slice**: "Refresh All" button on dashboard. Visual polish pass.

### Tasks

| # | Task | Files |
|---|------|-------|
| 6.1 | Add "Refresh All" button to dashboard that fires `POST /refresh-all` which searches all active trackers, then redirects to `/` | `backend/pages.py`, `frontend/templates/dashboard.html` |
| 6.2 | Add `POST /refresh-all` route — iterates active trackers, calls `search_and_store` for each, returns dashboard with updated summaries | `backend/pages.py` |
| 6.3 | Verify airline name column shows full name (check if fli `airline.name` returns code or full name; if code only, leave as-is for now) | `backend/sources/google_flights.py` |
| 6.4 | Final CSS polish: ensure consistent spacing, hover states, border-radius consistency | `frontend/static/app.css` |

### Key design decisions

- Refresh All: calls `search_and_store` sequentially for each active tracker (not parallel — to respect fli rate limiting). Shows a spinner while processing.
- The pages route `POST /refresh-all` replaces the entire dashboard body with updated content.

### What NOT to touch

- `backend/api.py`
- `backend/db.py`
- `backend/scheduler.py`
- `backend/models.py`

### Tests

No new tests for Phase 6. Verification via HTTP smoke test.

### Verification

```bash
# smoke test
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/refresh-all

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Test File Summary

| File | Tests | Phase |
|------|-------|-------|
| `tests/test_pages.py` | 8 (Phase 1) + 3 (Phase 2) = 11 | Phase 1–2 |
| `tests/test_delta.py` | 5 | Phase 3 |
| `tests/test_normalization.py` | 4 | Phase 4 |
| `tests/test_notification_log.py` | 6 | Phase 5 |

---

## Handoff Notes

### Key files to start with

| File | Purpose |
|------|---------|
| `frontend/templates/tracker.html` | Split into header + partial; Phase 1 entry point |
| `frontend/templates/partials/detail_content.html` | New partial — Phase 1 deliverable |
| `backend/pages.py` | Routes return partials instead of full pages; touched in Phases 1–5 |
| `frontend/static/app.css` | Layout fixes, new badge styles; touched in Phases 2–6 |
| `backend/scheduler.py` | `_evaluate_notifications` gets real body; Phase 5 |
| `backend/db.py` | New notification_log table + functions; Phase 5 |
| `backend/models.py` | Uppercase validator; Phase 4 |

### Implementation constraints

- `_build_detail_context` is the central context builder for the detail page. Changes to delta logic affect both the detail page AND the pages routes that call it.
- The `client` fixture in `conftest.py` mocks `search_and_store` at the module level. Tests for pages routes that indirectly call it must NOT bypass this mock — use `import backend.scheduler` (module reference pattern).
- DB path is always `os.environ["AIRFARE_DB_PATH"]` — never hardcode.
- Jinja2 environment in `pages.py` uses `cache_size=0` — if switching to Starlette's `Jinja2Templates`, test on Python 3.13 first.
- fli's `Airline.name` is an enum key — it returns the airline code (e.g., "VY"), not the full name. Check `leg.airline` for a `full_name` or similar attribute before investing effort in airline name display.

### Risks

- Chart.js time adapter: `chartjs-adapter-date-fns` requires `date-fns` as a peer dependency. The jsdelivr bundle includes it. Verify with a smoke test.
- The search-now route changes from returning `tracker.html` to `detail_content.html` — verify that the chart scripts included in the partial execute correctly when injected via HTMX `innerHTML` swap (HTMX does execute `<script>` tags by default).
- Refresh All with sequential `search_and_store` calls may be slow (each search takes 2–5 seconds). Consider a progress indicator or a note for the user.
