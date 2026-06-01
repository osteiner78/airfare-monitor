# 007 — Code Review: Full Codebase

**Reviewed**: All backend, frontend, and test files
**Date**: 2026-05-31
**Verdict**: Clean — no critical issues. Three correctness concerns worth addressing.

---

## 🟡 Important

### I1 — `best_price` in detail header includes missing flights

**File**: `backend/pages.py:174`
```python
best_price = min((f["flight"]["price"] for f in flights_with_delta), default=None)
```
`flights_with_delta` includes both current flights AND missing flights (from previous snapshot). The min price could be from a flight that no longer exists in the current search. The header shows "Best now: €33" but that price might not actually be bookable anymore.

**Fix**: Filter to only current flights:
```python
best_price = min((f["flight"]["price"] for f in flights_with_delta
                  if f.get("delta", {}).get("type") != "missing"), default=None)
```

**Confidence**: certain

---

## 🟡 Important

### I2 — Duplicated timestamp-splitting code in `_build_detail_context`

**File**: `backend/pages.py:147-160` and `:171-184`

The exact same 14-line timestamp parsing block appears twice — once for current flights, once for missing flights. Any change to the parsing logic must be made in two places.

**Fix**: Extract a helper function:
```python
def _split_timestamps(flight_dict):
    for key in ("departure_time", "arrival_time"):
        val = flight_dict.get(key)
        if val and "T" in str(val):
            ...
            flight_dict[key + "_date"] = _format_date(date_part)
            flight_dict[key + "_time"] = time_part + tz_suffix
```
Call from both loops.

**Confidence**: certain

---

### I3 — Duplicate CSS rules

**File**: `frontend/static/app.css`

Multiple duplicate declarations:
- `.route` at lines 137-140 AND 143 (exact duplicate, adjacent)
- `.best-price` at lines 133-136 AND 155-158 (different values! 1.125rem vs 1.25rem. Rule at 155 overrides rule at 133)
- `.card-body` at lines 125-128 AND 153-156 (margin-bottom 0.25rem vs 0.5rem. Rule at 153 overrides)
- `.gf-link:hover` at lines 447-449 AND at 450-451 (empty block at 450-451)
- `.book-link:hover` at 453-455 without any `.book-link` base rule (dead code)

The `.best-price` conflict means the card price font size is 1.25rem but the card-clickable `.best-price` is supposed to be 1.125rem. The duplicate at line 153 overrides line 133.

**Fix**: Remove all duplicate rules. Consolidate `.best-price` to use one consistent value. Remove dead `.book-link:hover` rule.

**Confidence**: certain

---

---

### I4 — `get_recent_logs` sorts by `id` instead of `created_at`

**File**: `backend/db.py:371`
```python
"SELECT * FROM system_logs ORDER BY id DESC LIMIT ?"
```
Auto-increment IDs are usually chronological, but if a log entry has a backdated `created_at` (manual insert, timezone issue), the ordering would be wrong. The user-visible ordering should match `created_at`.

**Fix**:
```python
"SELECT * FROM system_logs ORDER BY created_at DESC, id DESC LIMIT ?"
```

**Confidence**: likely

---

### I5 — `ensure_db_initialized` runs on every request

**File**: `backend/main.py:48-54`
```python
@app.middleware("http")
async def ensure_db_initialized(request: Request, call_next):
    path = get_db_path()
    if path not in _initialized_paths:
        await init_db(path)
        _initialized_paths.add(path)
    return await call_next(request)
```
The `path not in _initialized_paths` check is cheap (set lookup), but the middleware runs on every request including static files. After the first request, it's a no-op, but it's still executed.

**Impact**: Negligible for a personal tool. Mentioned for awareness — a production deployment might want to skip this for static file requests.

**Confidence**: speculative (no measurable performance issue)

---

## 🟢 Suggestions

### S1 — `.gitignore` doesn't protect the production database

**File**: `.gitignore` (check if exists)

There's no `.gitignore` entry for `data/airfare.db`. Only `data/.gitkeep` is tracked. A `git add -A` would accidentally commit the production database with real flight data.

**Fix**: Add `data/airfare.db` to `.gitignore`.

**Confidence**: certain

---

### S2 — `flight_key` test data doesn't match production values

**File**: `tests/test_fingerprint.py`

All fingerprint tests construct `FlightResult` with `airline="LX"`, `flight_number="LX1234"`. In production, `airline` is now "Vueling" (full name) and `flight_number` is "VY 6201" (code + number). The tests pass but don't validate the actual production pipeline from `_map_result → make_flight_key`.

**Fix**: No code change needed — this is a test coverage gap to address when the flight_key format is corrected (C1).

**Confidence**: likely

---

### S3 — `format_date` in Jinja2 and Python are separate implementations

**File**: `backend/pages.py:37-45` and `:48`

The `_format_date` function handles `ValueError` and `TypeError` gracefully, which is good. But `_format_date` is called both as a Jinja2 filter (`| format_date`) AND directly in Python code (line 159, 184). Both paths work but `strftime("%B %-d")` uses platform-dependent `%-d` (zero-padded day on some systems). macOS supports `%-d`, Linux uses `%-d` with glibc, but Windows doesn't.

**Impact**: Only affects Windows deployments. Our target is macOS/Linux.

**Confidence**: speculative

---

### S4 — Chart `no-data` fallback appends a `<p>` to the canvas parent

**File**: `frontend/static/charts.js:8-13`
```javascript
var noData = document.createElement("p");
noData.textContent = "No price data yet";
canvas.parentNode.appendChild(noData);
```
This adds a `<p>` element to `.chart-container`. On subsequent HTMX swaps, the chart container is replaced (outerHTML), so the `<p>` is removed naturally. But if `charts.js` runs multiple times on the same page (e.g., initial load then HTMX swap on a different target), the old `<p>` could remain.

**Impact**: Minor — HTMX swaps replace the entire `#detail-content` div, so this is generally safe.

**Fix**: Check if `noData` text already exists before appending.

**Confidence**: speculative

---

## Top 3 to fix first

1. **I1 — `best_price` includes missing flights** — shows inaccurate "Best now" price in detail header
2. **I2 — Duplicated timestamp-splitting code** — maintenance risk, easy extraction
3. **I3 — Duplicate CSS rules** — `.best-price` and `.card-body` have conflicting duplicate declarations

## Architectural concerns

- **CSS maintenance debt**: `app.css` has 573 lines with at least 5 duplicate rule blocks including conflicting values (`.best-price` declared at both 1.125rem and 1.25rem). The file has grown organically through 6+ plans. Consider CSS linting for v2.

## Test gaps

- No integration test that exercises the full pipeline: `fli search → _map_result → insert_flight_prices → _build_detail_context → render HTML`. All tests mock either `search_and_store` or operate at the unit level.
- No test for `_map_result` with real multi-leg flight data (fli returns multi-leg results as tuples).
- No test for the chart data format (`chart_datasets` JSON structure).
- No lighthouse/accessibility audit on the frontend.
