# 005 — Frontend Chart & Layout Fixes

## What was fixed

### Chart rendering
The chart was blank because:
1. **163 historical datasets** — `_build_detail_context` included every flight_key ever seen, not just current snapshot flights. Limited to `current_keys` from latest snapshot.
2. **Time scale adapter dependency** — Chart.js 4.x time scale requires `chartjs-adapter-date-fns` CDN. Switched to category scale with server-side formatted labels, eliminating adapter dependency.
3. **Ghost code cleanup** — removed `chartjs-adapter-date-fns` CDN from `detail_page.html` (no longer needed since switching to category scale).

### Duration formatting
Results table duration column changed from `95m` to `1h 35m` format (minutes → hours:minutes).

### Header layout
- Best now / Historical best prices moved to right side of detail header (flexbox layout).
- Renamed "All-time best" → "Historical best".
- Flight date font increased to 1.05rem.

### Date formatting
- `_format_date` filter changed from `%b` (abbreviated month, e.g. "Jul") to `%B` (full month, e.g. "July").
- Results table departure/arrival dates now pass through `_format_date` server-side, showing "July 29" instead of "2026-07-29".

### Google Flights link
- Removed non-functional `&tt=o` and `&flight_type=one_way` parameters.
- "One-way" embedded directly in the natural language search query (`q=One-way+flights+to+...`).
- Same pattern applied to both `detail_page.html` template and `google_flights.py` source.

### Code cleanup
- Deleted `frontend/templates/partials/detail_content.html` (dead code from plan 003 merge).
- Removed duplicate `.detail-header .date` CSS rule.
- Removed `chartjs-adapter-date-fns` CDN from `detail_page.html`.

## Files changed

| File | Change |
|------|--------|
| `backend/pages.py` | Chart limited to current snapshot flights; date pre-formatting via `_format_date`; `%B` month format |
| `frontend/static/charts.js` | Category scale replacing time scale; explicit canvas sizing; date parsing fallback |
| `frontend/templates/partials/detail_page.html` | Header flexbox layout; "Historical best" rename; Google Flights link with "One-way" in query; removed adapter CDN |
| `frontend/templates/partials/results_table.html` | Duration `Xh Ym` format; removed Link column |
| `frontend/templates/partials/tracker_card.html` | Restructured click zone vs button zone; date formatting |
| `frontend/static/app.css` | `.detail-header-top` flexbox; date font size; removed duplicate CSS |
| `backend/sources/google_flights.py` | One-way Google Flights URL in search query |
| `frontend/templates/partials/detail_content.html` | Deleted (dead code) |

## Verification

```
90 passed, 1 deselected in 1.17s
```

Chart now renders with category scale, ~10-20 datasets (current snapshot only), no adapter dependency.
