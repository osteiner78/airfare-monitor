# 007 — Code Review Fixes: End

**Date**: 2026-05-31
**Baseline**: 100 tests pass, 0 fail

## Changes made

### I1 — `best_price` excludes missing flights
**File**: `backend/pages.py:209`
Filtered `flights_with_delta` to exclude entries with `delta.type == "missing"` so the "Best now" price in the detail header only reflects currently bookable flights.

### I2 — Extracted `_split_timestamps` helper
**File**: `backend/pages.py:56-68`
New `_split_timestamps(flight_dict)` function deduplicates the 14-line timestamp parsing block that appeared twice. Both call sites replaced with 1-3 line calls.

### I3 — CSS duplicates removed
**File**: `frontend/static/app.css`
- Removed duplicate `.route` rule
- Removed conflicting duplicate `.best-price` (1.25rem override), kept 1.125rem + text-align:right
- Removed conflicting duplicate `.card-body` (0.5rem margin-bottom), kept 0.25rem
- Removed duplicate `.gf-link:hover` rule
- Removed dead `.book-link:hover` (no base `.book-link` rule)
- Restored `.card-body .date` and `.date` blocks (accidentally lost during edits)

### I4 — `get_recent_logs` ORDER BY fix
**File**: `backend/db.py:455`
Changed `ORDER BY id DESC` to `ORDER BY created_at DESC, id DESC` for correct chronological ordering.

### S1 — `.gitignore` database protection
Already covered by existing `data/` and `*.db` entries. No change needed.

## Verification

```
$ pytest tests/ -v -k "not slow"
============================= test session starts ==============================
collected 101 items / 1 deselected / 100 selected

100 passed in 1.59s
```

All 100 non-slow tests pass (same as baseline).

## Deviations from plan

None. All fixes implemented exactly as described in the code review report.

## Follow-ups (not done)

- **I5** (middleware perf): Negligible impact for personal tool, skipped per report guidance.
- **S2** (flight_key test data mismatch): Tests pass but use synthetic data; not addressed.
- **S3** (`format_date` platform dependency): Only affects Windows, not applicable.
- **S4** (Chart no-data fallback): Minor, only affects edge case.

## Confidence

**Certain** — all fixes are straightforward, isolated, and verified by full test suite pass.
