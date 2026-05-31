# 003 — UX Corrections

## What this fixes

Plan 002 was implemented functionally but missed several UX details and had one critical architectural gap:

1. **Form bypasses uppercase validator** — Pydantic validator only applies to JSON API route, not the HTML form POST. Lowercase codes silently fail.
2. **Pause on detail page doesn't update the header** — header (badge, button text) is outside the HTMX swap target.
3. **Chart blank** — date format mismatch or script execution order.
4. **Table too narrow** — container is 720px but table needs more room.
5. **No airline name column** — currently merged into Flight column. Need separate column with full airline name from fli.
6. **No arrival date** — only time shown, missing date for long-haul/multi-day flights.
7. **Search Now button** — below the chart, should be at top.
8. **Card layout** — date under route at left, price at right.
9. **Booking URLs** — fli provides `booking_token` (can construct Google Flights link) and `primary_airline_name`.

---

## Fix 1 — Uppercase normalization for form POST

Root cause: `backend/pages.py:62` passes `form["origin"]` raw to `create_tracker()`. The Pydantic `TrackerCreate` uppercase validator only runs on `POST /api/trackers`, not on `POST /`.

### Fix
In `backend/pages.py`, add_tracker route: call `.upper()` on origin and destination before passing to `create_tracker()`.

```python
# pages.py:58-66
@router.post("/")
async def add_tracker(request: Request):
    form = await request.form()
    tracker = await create_tracker(
        origin=form["origin"].upper(),
        destination=form["destination"].upper(),
        ...
```

**File**: `backend/pages.py` (lines 58-66)

---

## Fix 2 — Pause updates the detail header

Root cause: `tracker.html:13-16` pause button targets `#detail-content`. The `detail-header` (badge, button text) is OUTSIDE `#detail-content` and never re-rendered.

### Fix
Change the pause button `hx-target` from `#detail-content` to `#detail-page` (a new wrapper). The toggle route returns a partial that includes both the header and content.

Alternatively (simpler): wrap the entire detail page content in `<div id="detail-content">` (including the header), so the `outerHTML` swap replaces everything. Update `toggle-detail` route to return a partial with header + content.

Simplest approach: in `tracker.html`, wrap `detail-header` + `detail_content.html` in `<div id="detail-content">`. Change toggle route to return a complete detail view partial.

```html
<!-- tracker.html -->
<div id="detail-content">
    <div class="detail-header">...</div>
    {% include "partials/detail_content.html" %}
</div>
```

The toggle-detail route should return a partial with both header and content. Create `partials/detail_page.html` that contains:
- detail-header (with updated active badge + button text)
- detail_content.html include

**Files**: `frontend/templates/tracker.html`, `backend/pages.py` (toggle-detail route), new `frontend/templates/partials/detail_page.html`

---

## Fix 3 — Chart rendering

Root cause: SQLite stores timestamps as `"YYYY-MM-DD HH:MM:SS"` (space separator). The Chart.js time scale with date-fns adapter can parse this, but the T-based ISO 8601 format is more reliable.

Additionally, `charts.js` runs as an IIFE immediately when the script loads. On initial page load via `tracker.html` (which extends base.html and includes detail_content.html), the script tags are inside `{% block content %}` within `<body>`, so `getElementById("price-chart")` should find the canvas.

### Fix
Format timestamps as ISO 8601 in `_build_detail_context` when building chart data. Replace space with "T" in the searched_at value.

```python
# pages.py:151
"x": row["searched_at"].replace(" ", "T"),
```

**File**: `backend/pages.py` (line 151)

---

## Fix 4 — Wider table container

Root cause: `.container { max-width: 720px }` is too narrow for 9+ columns.

### Fix
Increase max-width to `960px` for the detail page. Add a `.detail-container` class with wider max-width for the detail page, or increase the global container to 960px.

```css
/* Wider on detail page */
.detail-container {
    max-width: 960px;
}
```

For the dashboard, keep 720px. For the detail page, use 960px.

**Files**: `frontend/static/app.css`, `frontend/templates/tracker.html` (change class)

---

## Fix 5 — Airline name column

Root cause: fli provides `primary_airline_name` (e.g., "Vueling") on FlightResult, but the source never captures it.

### Fix
1. In `GoogleFlightsSource._map_result`: capture `r.primary_airline_name` into FlightResult (the dataclass doesn't have this field — need to add a way to pass it through, OR store it in the `airline` field differently).

Since FlightResult is a fixed dataclass, use the `airline` field to store the FULL airline name, and compute the code separately if needed. Or better: keep current `airline` as code, add the full name to `legs_json` and extract it server-side.

Simplest: add `airline_name` as a new field to the flight_prices INSERT (need schema migration — avoid). Instead, store airline full name as a separate key in the prices dict and pass it through the context.

Actually simplest: just render `primary_airline_name` from the legs data. In `_map_result`, the `airlines` codes are already stored in the `airline` field. Add the full name to the `legs_json` data dict for the first leg.

Wait — the easiest approach without schema changes: in `_build_detail_context`, for each flight, extract the first leg's airline name from `legs_json` if available. But `legs_json` is a JSON string.

Actually the simplest fix: the `airline` field currently stores codes like "VY". We can repurpose it or add the name. But the cleanest approach without DB migration:

In `_map_result`, build a dict with both code and name and encode them in `legs_json`. Then in `_build_detail_context`, decode `legs_json` and extract the name.

OR even simpler: put the full name in the `airline` field. Change `_map_result` from:
```python
airlines = "+".join(leg.airline.name for leg in legs)
```
to:
```python
airline_name = r.primary_airline_name or (legs[0].airline.value if legs else "")
airline_code = "+".join(leg.airline.name for leg in legs)
```

Then store `airline_name` as `airline` in FlightResult, and `airline_code` as a new attribute... but FlightResult doesn't have a separate field.

Simplest real approach: store airline name in the `airline` field (replacing the code), and put the code in `legs_json`. Then update the results table to show airline name in the first column and codes in the Flight column.

OR: just set `airline = r.primary_airline_name` and keep flight_number. The Flight column already shows both. Remove the duplicate.

Actually, for the cleanest fix: in `_map_result`, use `primary_airline_name` as the `airline` value (full name). The existing `Flight` column becomes `{{ item.flight.flight_number }}`. Add a new first column `Airline` showing `{{ item.flight.airline }}`.

In `results_table.html`:
```html
<th>Airline</th>
<th>Flight</th>
<th>Date</th>
...
```

```html
<td>{{ item.flight.airline or "—" }}</td>
<td>{{ item.flight.flight_number or "—" }}</td>
...
```

**Files**: `backend/sources/google_flights.py` (_map_result), `frontend/templates/partials/results_table.html`

---

## Fix 6 — Arrival date column

Root cause: `_build_detail_context` computes `arrival_time_date` and `arrival_time_time` but `results_table.html` only renders `arrival_time_time`.

### Fix
In `results_table.html`, split the Arrival column into Date and Time, or add an Arrival Date column before Arrival Time.

```html
<th>Dep Date</th>
<th>Dep Time</th>
<th>Arr Date</th>
<th>Arr Time</th>
```

And render:
```html
<td>{{ item.flight.get("departure_time_date", "—") }}</td>
<td>{{ item.flight.get("departure_time_time", "—") }}</td>
<td>{{ item.flight.get("arrival_time_date", "—") }}</td>
<td>{{ item.flight.get("arrival_time_time", "—") }}</td>
```

**File**: `frontend/templates/partials/results_table.html`

---

## Fix 7 — Search Now button at top

Root cause: button is inside `.results-section > .results-header`, below the chart.

### Fix
Move the Search Now button to the `detail-header` area or create a top action bar. Put it next to the Pause/Resume and Delete buttons in the `detail-controls` div.

```html
<div class="detail-controls">
    <span class="badge ...">Active</span>
    <button hx-post="/trackers/{{ id }}/search" ...>Search Now</button>
    <button hx-patch="/trackers/{{ id }}/toggle-detail" ...>Pause</button>
    <button ...>Delete</button>
</div>
```

Update the `hx-target` to `#detail-content` and `hx-swap="outerHTML"`. Remove the button from `detail_content.html`.

**Files**: `frontend/templates/tracker.html`, `frontend/templates/partials/detail_content.html`

---

## Fix 8 — Card layout restructure

Root cause: the card layout doesn't match user request.

Current layout:
```
[GVA -> BCN]              [Flight date: 2026-09-15]
[33.00 EUR]               [Active]
[no change] [2h ago]      [Pause] [Delete]
```

Requested layout:
```
[GVA -> BCN]                          [33.00 EUR]
[Flight date: 2026-09-15]             [Active]
[no change] [2h ago]                  [Pause] [Delete]
```

### Fix
Restructure `tracker_card.html`:
- Row 1: route (left) + price (right) — use `.card-header` with `justify-content: space-between`
- Row 2: flight date label (left) + active badge (right) — use `.card-body`
- Row 3: delta + last-checked (left) + pause/delete (right) — use `.card-footer`

Remove the existing `.card-body` layout that puts price and badge together. Price goes to the right of the header row.

Updated CSS: price in header, no separate price line.

**Files**: `frontend/templates/partials/tracker_card.html`, `frontend/static/app.css`

---

## Fix 9 — Booking URLs

Root cause: `_map_result` set `booking_url=""`. But fli provides `booking_token` on FlightResult (a JSON-encoded string).

### Fix
Store `booking_token` in the `booking_url` field (or construct a Google Flights URL). The token is a JSON array. URL format: `https://www.google.com/travel/flights?t={base64_encoded_token}` — but the token is already a complex format.

Simpler: store the booking_token as `booking_url` and render it as a deep-link. Or use it with `get_booking_options` to get actual booking links.

For now, just store `r.booking_token` as the `booking_url` value. In the results table, render as "Book" link with the token.

Actually, `booking_token` is a JSON string like `'["CAISA0VVUhoDCKAZ..."]'`. Google Flights doesn't have a simple URL format with this token. But we can generate a Google Flights search URL:

`https://www.google.com/travel/flights?q=Flights+to+BCN+from+GVA+on+2026-09-15`

This is a fallback — a direct Google Flights search link. Not a booking link, but a useful link to check current prices.

Better approach: store the `booking_token` and construct a deep-link. The Google Flights web URL with the booking token isn't straightforward. Use the search URL as fallback.

In `_map_result`:
```python
booking_url=f"https://www.google.com/travel/flights?q=Flights+to+{dest}+from+{origin}+on+{depart_date}"
```

**Files**: `backend/sources/google_flights.py` (_map_result, pass origin/dest/date to construct URL)

---

## Fix 10 — Timezone clarity

Root cause: fli returns times with offsets (e.g., `2026-09-15T09:45:00+02:00`). The current code strips timezone info in `_build_detail_context` without indicating that times are local. For long-haul flights crossing time zones, this is confusing.

### Fix
Preserve the timezone offset in the displayed time. In `_build_detail_context`, when splitting ISO timestamp, include the UTC offset in the time display (e.g., `09:45 (+02:00)`). Add small footnote text: "All times local to departure/arrival airport."

**Files**: `backend/pages.py` (_build_detail_context time parsing), `frontend/templates/partials/results_table.html`

---

## Files modified

| File | Fixes |
|------|-------|
| `backend/pages.py` | Fix 1 (uppercase), Fix 2 (toggle route returns header+content), Fix 3 (ISO date format in chart data) |
| `frontend/templates/tracker.html` | Fix 2 (wrap in new detail-content), Fix 7 (Search Now in header) |
| `frontend/templates/partials/detail_content.html` | Fix 7 (remove Search Now button), Fix 3 (already has adapter CDN) |
| `frontend/templates/partials/detail_page.html` | NEW — Fix 2 (header + content partial for toggle route) |
| `frontend/templates/partials/results_table.html` | Fix 5 (airline name column), Fix 6 (arrival date), Fix 9 (booking link) |
| `frontend/templates/partials/tracker_card.html` | Fix 8 (card layout) |
| `frontend/static/app.css` | Fix 4 (wider detail container), Fix 8 (card layout) |
| `backend/sources/google_flights.py` | Fix 5 (airline full name), Fix 9 (booking URL) |

## What NOT to touch

- `backend/db.py` — no schema changes needed
- `backend/models.py` — already correct
- `backend/api.py` — no API changes needed
- `backend/scheduler.py` — already correct
- `frontend/static/charts.js` — already correct
- `tests/` — no test changes needed (existing tests verify non-regression)
