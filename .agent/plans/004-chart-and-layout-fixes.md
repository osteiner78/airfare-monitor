# 004 — Chart Debug, Layout Fixes, Booking Links

## What this fixes

Plan 003 introduced a partial-merging architecture where `detail_page.html` wraps header + chart + table inside `#detail-content`, and `detail_content.html` remains as a duplicate. This creates three bugs:

1. **Search Now removes the header** — `search_now` route returns `detail_content.html` (no header) into the `#detail-content` swap target that includes the header.
2. **Chart blank** — chart scripts exist in both `detail_page.html` and `detail_content.html`. HTMX `outerHTML` swap creates a new canvas but old Chart instance is orphaned. Also possible data format issue.
3. **Dashboard pause navigates to detail** — card `hx-get` + child button `hx-patch` event conflict.

Plus remaining UX gaps from plan 003 feedback.

---

## Phase 1 — Delete dead partial + fix search-now route

### Tasks

| # | Task | Files |
|---|------|-------|
| 1.1 | Delete `frontend/templates/partials/detail_content.html` — no longer used anywhere | Delete file |
| 1.2 | Change `search_now` route to return `detail_page.html` instead of `detail_content.html` | `backend/pages.py` |
| 1.3 | Verify `tracker.html` uses `{% include "partials/detail_page.html" %}` (already does from plan 003) | Verify only |
| 1.4 | Verify `toggle-detail` route returns `detail_page.html` (already does from plan 003) | Verify only |
| 1.5 | Run tests to confirm no references to deleted file | Tests |

### What NOT to touch

- `frontend/templates/tracker.html` — already correct
- `frontend/static/charts.js`
- `backend/db.py`
- `backend/scheduler.py`

### Verification

```bash
pytest tests/ -v -k "not slow"
# all 87 tests must pass, detail_page_does_not_embed_full_html_in_detail_content should still pass
```

---

## Phase 2 — Debug and fix chart rendering

### Tasks

| # | Task | Files |
|---|------|-------|
| 2.1 | Add a hardcoded dummy data chart test: create a new `frontend/static/chart_test.html` that loads Chart.js + adapter + dummy data to confirm CDN/adapter/rendering pipeline works end-to-end | `frontend/static/chart_test.html` (temporary debug) |
| 2.2 | Fix chart data format: ensure `searched_at` values have "T" separator (already done in `pages.py:154`). Add fallback parsing in `charts.js` for non-ISO dates | `frontend/static/charts.js` |
| 2.3 | Add defensive check in `charts.js` — if `window.chartData` is empty array, render "No price data yet" text on canvas instead of blank chart | `frontend/static/charts.js` |
| 2.4 | Verify `chartjs-adapter-date-fns` CDN URL is correct and adapter loads before Chart.js in `detail_page.html` (already correct, lines 50-53) | Verify only |
| 2.5 | Add `destroy()` call for previous Chart instance before creating new one, to prevent memory leaks on HTMX swaps. Check if canvas already has a Chart instance | `frontend/static/charts.js` |
| 2.6 | Delete `chart_test.html` after confirming pipeline works | Delete file |

### Key design decisions

- Chart.js persists instances on removed canvases. Before creating a new chart, check `Chart.getChart(canvas)` and call `.destroy()` on any existing instance.
- Dummy data uses hardcoded timestamps and prices to isolate the rendering pipeline from data issues.
- If no data exists, render text on canvas via `ctx.fillText("No price data yet", ...)` instead of an empty chart.

### What NOT to touch

- `backend/pages.py` (chart data building is already correct)
- `frontend/templates/partials/detail_page.html` (scripts are correct)

### Verification

```bash
pytest tests/ -v -k "not slow"
# regression unchanged
```

Manual: open `chart_test.html` in browser, confirm chart renders with dummy data. Then open detail page with real data, confirm chart renders.

---

## Phase 3 — Fix dashboard pause + restructure card

### Tasks

| # | Task | Files |
|---|------|-------|
| 3.1 | Restructure `tracker_card.html`: remove `hx-get` from card div. Instead, wrap route + date + price + badge in a clickable `<a>` tag (or div with `hx-get`) that navigates to detail. Leave `.card-actions` (pause/delete) completely outside the click zone — no inheritance cancel needed | `frontend/templates/partials/tracker_card.html` |
| 3.2 | Update card CSS for new structure — ensure the clickable area has `cursor: pointer` and hover effect. Buttons keep their own styling | `frontend/static/app.css` |
| 3.3 | Adjust card layout per user request: route + price on top row (price right-aligned), date + badge on second row, delta + last-checked on third row with actions | `frontend/templates/partials/tracker_card.html` |

### Key design decisions

- The clickable area wraps route, date, price, badge (non-interactive content). Buttons are adjacent siblings outside the click area.
- No `hx-get=""` cancel needed — structural separation eliminates the need.

### What NOT to touch

- `backend/pages.py`
- `backend/db.py`

### Verification

```bash
pytest tests/ -v -k "not slow"
# all 87 pass, test_toggle_returns_card_partial still passes (card structure changes but partial still renders)
```

---

## Phase 4 — Add best price + historical best to detail header

### Tasks

| # | Task | Files |
|---|------|-------|
| 4.1 | Modify `_build_detail_context`: add `best_price` (lowest price in current snapshot) and `historical_best_price` (lowest price across all snapshots). Query all-time minimum from DB or compute from history data | `backend/pages.py` |
| 4.2 | Add all-time minimum query to DB: `get_historical_best_price(tracker_id)` — `SELECT MIN(price) FROM flight_prices WHERE tracker_id = ?` | `backend/db.py` |
| 4.3 | Render "Best now: €33.00 / All-time best: €33.00" in `detail_page.html` header section, below the route title | `frontend/templates/partials/detail_page.html` |
| 4.4 | Style the price display in header | `frontend/static/app.css` |

### Key design decisions

- `historical_best_price` is the absolute minimum across ALL flight_prices rows for this tracker. Not per-flight — the overall best deal ever seen.
- `best_price` is the minimum in the current (latest) snapshot — same value shown on the dashboard card.

### What NOT to touch

- `backend/models.py`
- `backend/api.py`
- Dashboard card template

### Tests

New file: `tests/test_best_price.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_get_historical_best_price_returns_min_for_tracker_with_data` | Fails — function not yet implemented |
| NEW-BEHAVIOR | `test_get_historical_best_price_returns_none_for_tracker_with_no_data` | Fails |
| FAILURE-MODE | `test_get_historical_best_price_returns_none_for_nonexistent_tracker` | Fails |

### Verification

```bash
pytest tests/test_best_price.py -v
# 3 NEW-BEHAVIOR + FAILURE-MODE must FAIL before implementation

pytest tests/ -v -k "not slow"
# full regression passes
```

---

## Phase 5 — Booking link + date formatting + table width

### Tasks

| # | Task | Files |
|---|------|-------|
| 5.1 | Change `_map_result` to construct a one-way Google Flights URL: `https://www.google.com/travel/flights?q=Flights+to+{dest}+from+{origin}+on+{depart_date}&curr={currency}&tt=o` (tt=o = one-way). Remove per-flight Link column | `backend/sources/google_flights.py` |
| 5.2 | Remove "Link" column from results table. Add a single "Search on Google Flights" link button in `detail_page.html` header, next to Search Now | `frontend/templates/partials/results_table.html`, `frontend/templates/partials/detail_page.html` |
| 5.3 | Date formatting: parse `depart_date` (YYYY-MM-DD) into "Jun 6" format. Add server-side formatting function in `pages.py`, use in templates. Show year only if not current year | `backend/pages.py`, templates |
| 5.4 | Remove "Flight date:" label from tracker_card.html (line 17). Show bare formatted date | `frontend/templates/partials/tracker_card.html` |
| 5.5 | Widen detail container: `.detail-container { max-width: 1100px }` to fit 10 columns comfortably | `frontend/static/app.css` |
| 5.6 | Remove "Flight date:" label from `detail_page.html` header | `frontend/templates/partials/detail_page.html` |
| 5.7 | Add TODO.md entry: "Replace airline codes with airline logos/icons" | `TODO.md` |
| 5.8 | Add TODO.md entry: "Fetch per-flight booking URLs using fli's get_booking_options()" | `TODO.md` |

### Key design decisions

- One-way URL uses `&tt=o` parameter to force one-way mode in Google Flights.
- Date formatting: Python `datetime.strptime` + `strftime("%b %-d")` for display. Add year `strftime("%b %-d, %Y")` only if year != current year.
- Link column removed from table — booking link becomes a tracker-level feature.

### What NOT to touch

- `backend/db.py`
- `backend/scheduler.py`
- `backend/api.py`

### Tests

No new tests. Phase 5 is layout/formatting changes verified by smoke test.

### Verification

```bash
pytest tests/ -v -k "not slow"
# all pass

# Smoke test: check Google Flights link is one-way
curl -s http://localhost:8000/trackers/1 | grep -o "tt=o"
```

---

## Phase 6 — Polish

### Tasks

| # | Task | Files |
|---|------|-------|
| 6.1 | Verify "times are all local" note in results table header (from plan 003 fix 10 — was implemented) | Verify |
| 6.2 | Run full regression test suite | Tests |
| 6.3 | Manually smoke test: create tracker, search, verify chart renders, verify pause works, verify booking link is one-way | Manual |
| 6.4 | Save verification output to `.agent/reports/004-phase-6.md` | Report |

### Verification

```bash
pytest tests/ -v -k "not slow"
# all tests pass
```

---

## Test Files Summary

| File | Tests | Phase |
|------|-------|-------|
| `tests/test_best_price.py` | 3 | Phase 4 |

No other new tests — existing suite covers non-regression for routes and DB.

---

## Handoff Notes

### Key files

| File | Purpose |
|------|---------|
| `frontend/templates/partials/detail_page.html` | Central detail partial — all HTMX routes return this |
| `frontend/templates/partials/detail_content.html` | DELETE — dead code, superseded by detail_page.html |
| `frontend/templates/partials/tracker_card.html` | Restructured to separate click zone from button zone |
| `backend/pages.py` | search_now returns detail_page.html, date formatting, best price context |
| `backend/db.py` | New get_historical_best_price function |
| `frontend/static/charts.js` | Chart instance cleanup, empty-state text, date fallback parsing |

### Constraints

- `_build_detail_context` is the central context builder — add best_price fields here, not in routes
- DB path always from `os.environ["AIRFARE_DB_PATH"]`
- Jinja2 cache_size=0 workaround still applies
- `import backend.scheduler` module-reference pattern for mocks
