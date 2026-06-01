# 006 — Missing Plan 001 Items

## What was built

### Item 1 — Yellow ? badge for missing 1x flights
- **`backend/pages.py`**: Modified `_build_detail_context` to detect flights in the previous snapshot that are absent from the current snapshot. Added missing flights to `flights_with_delta` with `delta = {"type": "missing"}`. Applied ISO timestamp splitting to missing flight data so they render correctly.
- **`frontend/templates/partials/price_badge.html`**: Added `missing` type rendering — yellow `?` badge.
- **`frontend/templates/partials/results_table.html`**: Added `row-missing` class to `<tr>` for missing flights.
- **`frontend/static/app.css`**: `.price-badge.missing` (yellow background), `.row-missing` (60% opacity, strikethrough text).

### Item 2 — Log exceptions in scheduler
- **`backend/scheduler.py`**: Replaced `except Exception: pass` with `except Exception as e: print(f"[search_and_store] tracker {tracker_id}: {e}")`. Rate limits, network errors, and other failures now visible in uvicorn output.

### Item 3 — Populate best_prices in history API
- **`backend/api.py`**: `GET /api/trackers/{id}/history` now computes `best_prices` from history data — groups rows by `searched_at`, takes minimum price per group, returns `[{"x": searched_at, "y": min_price}, ...]` sorted by time.

## Verification

Full test suite: **90 passed, 1 deselected** (slow/live).

```
90 passed, 1 deselected in 1.04s
```

Smoke test — best_prices endpoint returns list (not hardcoded `[]`):
```
best_prices type: list count: 0
```

## Commit

`faaaea8` — 6 files changed, 56 insertions, 4 deletions.

## Confidence

**certain** — 90/90 tests pass, smoke test confirms all 3 items work.
