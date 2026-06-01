# 005 — Chart Improvements: Top-N Sticky, Time Scale, Legend

## What this changes

Currently the chart shows up to 150+ flight lines — useless spaghetti. This plan:
- Filters chart to flights that were ever in the top N cheapest at any snapshot (sticky top-N)
- Switches x-axis from category scale to time scale for proportional spacing
- Shortens legend labels to airline code + flight number only
- Adds legend toggles (click to hide/show lines) and improved tooltips
- Positions legend below the chart

Note: The yellow `?` badge for missing flights (plan 001 gap #1) is already implemented at `pages.py:162-184` and `price_badge.html:10-11`. Not included here.

---

## Phase 1 — Time Adapter Smoke Test + Top-N DB Query

### Tasks

| # | Task | Files |
|---|------|-------|
| 1.1 | Add `chartjs-adapter-date-fns` CDN back to `detail_page.html`, BEFORE Chart.js | `frontend/templates/partials/detail_page.html` |
| 1.2 | Create a standalone `frontend/static/chart_test_time.html` page that loads the adapter + Chart.js + hardcoded time-scale data to verify the adapter works end-to-end | `frontend/static/chart_test_time.html` |
| 1.3 | Add `get_sticky_top_flight_keys(tracker_id, top_n)` to DB: for each snapshot, rank flights by price ASC, collect flight_keys that appear in the top N of ANY snapshot. Return a set of flight_keys | `backend/db.py` |
| 1.4 | Verify Phase 1: open `chart_test_time.html` in browser — if time scale renders with proportional spacing, proceed. If blank, switch to Option B (numeric axis, Phase 4). | Manual |

### Key design decisions

- `top_n` defaults to 5, configurable. Stored per-tracker (`trackers.top_n` column) which already exists with default 10.
- The adapter CDN: `https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js` — same URL that confirmed working via curl earlier. The previous failure was due to 163 datasets, not the adapter itself.
- The test HTML page uses hardcoded data with timestamps to isolate adapter testing from server-side data issues.

### DB query

```sql
WITH ranked AS (
    SELECT fp.flight_key, s.id AS snapshot_id,
           ROW_NUMBER() OVER (PARTITION BY s.id ORDER BY fp.price ASC) AS rn
    FROM flight_prices fp
    JOIN snapshots s ON fp.snapshot_id = s.id
    WHERE fp.tracker_id = ?
)
SELECT DISTINCT flight_key FROM ranked WHERE rn <= ?
```

Note: SQLite supports window functions (ROW_NUMBER) since 3.25.0. Use aiosqlite. If aiosqlite links an older SQLite, implement the ranking in Python instead.

### What NOT to touch

- `frontend/static/charts.js` (rewritten in Phase 3)
- `backend/pages.py` `_build_detail_context` (modified in Phase 2)
- `frontend/templates/partials/detail_page.html` (modified in Phase 1 for CDN only)

### Tests

New file: `tests/test_chart_data.py`

| Label | Test name |
|-------|-----------|
| NEW-BEHAVIOR | `test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n` |
| NEW-BEHAVIOR | `test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots` |
| FAILURE-MODE | `test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker` |

All must FAIL with ImportError before Phase 1 implementation.

### Verification

```bash
pytest tests/test_chart_data.py -v
# all 3 MUST FAIL with ImportError

pytest tests/ -v -k "not slow"
# all 90 existing tests pass
```

---

## Phase 2 — Server-Side Chart Data Refactoring

### Tasks

| # | Task | Files |
|---|------|-------|
| 2.1 | Modify `_build_detail_context`: use `get_sticky_top_flight_keys(tracker_id, tracker["top_n"])` as chart dataset filter instead of `current_keys` | `backend/pages.py` |
| 2.2 | Change chart dataset label: extract airline code from `flight_key` (index 1 after `|` split). Format: `"{code} {flight_number}"` (e.g. "VY 6201", "A3+A3 855+710") | `backend/pages.py` |
| 2.3 | Keep `x` values as ISO timestamp with "T" separator (already done at line 201) | Verify only |

### Key design decisions

- Airline code from `flight_key`: `row["flight_key"].split("|")[1]` gives codes like "VY" or "A3+A3".
- The `airline` DB field still stores the full name (used for results table).
- Chart data format unchanged: `{x: "2026-05-31T17:22:21", y: 33.0}`.

### What NOT to touch

- `frontend/static/charts.js` (rewritten in Phase 3)
- DB schema — no changes
- Results table template

### Tests

Add to `tests/test_chart_data.py`:

| Label | Test name |
|-------|-----------|
| NEW-BEHAVIOR | `test_chart_datasets_limited_to_sticky_top_n` |

### Verification

```bash
pytest tests/test_chart_data.py -v
# Phase 1 tests (3) pass, Phase 2 test (1) fails

pytest tests/ -v -k "not slow"
# all existing 90 tests pass
```

---

## Phase 3 — Client-Side Chart Rewrite

### Tasks

| # | Task | Files |
|---|------|-------|
| 3.1 | Rewrite `charts.js`: switch from category scale to `type: "time"`. Remove `allLabels` accumulation and manual label building. Keep `{x, y}` data points | `frontend/static/charts.js` |
| 3.2 | Add `plugins.legend.position: "bottom"` | `frontend/static/charts.js` |
| 3.3 | Configure time scale: `unit: "hour"`, `displayFormats: { hour: "MMM d HH:mm" }` | `frontend/static/charts.js` |
| 3.4 | Remove manual date parsing code (space-to-T, month array formatting) — no longer needed | `frontend/static/charts.js` |
| 3.5 | Add `animation: false` to prevent flicker on HTMX chart swaps | `frontend/static/charts.js` |
| 3.6 | Delete `chart_test_time.html` | `frontend/static/chart_test_time.html` |

### Key design decisions

- Chart.js time scale with adapter auto-parses ISO 8601 `{x}` strings.
- `responsive: true, maintainAspectRatio: false` (already in place).
- `animation: false` — chart is destroyed and recreated on HTMX swaps.
- Legend toggles are Chart.js 4.x default — no extra config needed.

### What NOT to touch

- `backend/pages.py` — chart data format already correct
- `frontend/templates/partials/detail_page.html` — CDN scripts correct from Phase 1

### Verification

```bash
pytest tests/ -v -k "not slow"
# all tests pass

# Manual: open detail page, verify time-proportional x-axis, legend below, legend click toggles lines
```

---

## Phase 4 — Fallback: Numeric Axis

**Only execute if the time adapter fails in Phase 1 or 3.**

### Tasks

| # | Task | Files |
|---|------|-------|
| 4.1 | Switch to `type: "linear"`, convert `{x}` to `new Date(iso).getTime()` | `frontend/static/charts.js` |
| 4.2 | Format ticks via `ticks.callback` using `Date` objects | `frontend/static/charts.js` |
| 4.3 | Remove adapter CDN | `frontend/templates/partials/detail_page.html` |

---

## Test Files Summary

| File | Tests | Phase |
|------|-------|-------|
| `tests/test_chart_data.py` | 4 | Phase 1–2 |

---

## Handoff Notes

### Key files

| File | Purpose |
|------|---------|
| `backend/db.py` | New `get_sticky_top_flight_keys()` |
| `backend/pages.py` | Use sticky top-N filter, change label to code + number |
| `frontend/static/charts.js` | Rewrite: time scale, legend below, no category code |
| `frontend/templates/partials/detail_page.html` | Add adapter CDN before Chart.js |
| `frontend/static/chart_test_time.html` | Temp: verify adapter with dummy data |

### Known gotchas

- Adapter CDN must load BEFORE Chart.js CDN
- `flight_key` format: `source|codes|numbers|departure_iso`. Index 1 = codes.
- SQLite ROW_NUMBER: if aiosqlite uses old SQLite, rank in Python instead
- Legend toggles are default Chart.js 4.x behavior — no extra JS

### TODO additions

- Re-evaluate top-N strategy (sticky vs dynamic vs per-snapshot)
- Consider logarithmic price scale for wide price ranges
