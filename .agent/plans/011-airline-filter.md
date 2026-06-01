# Plan 011 — Airline filter for tracker detail sidebar

## Context

The tracker detail page (`/trackers/{id}`) has a client-side filter sidebar (plan 010) with **max stops** and **max duration** controls that dynamically filter the results table and price chart. We are adding a third control: an **airline filter** — a checklist of every airline appearing in the current results, each with a checkbox, so the user can narrow the table and chart to selected carriers.

The change is small and slots into the existing plan-010 machinery: the server already ships `window.allFlights` (full per-flight history + filter facets) and an inert, data-bounded sidebar; `frontend/static/filters.js` makes it live by filtering `allFlights`, recomputing the price-rank top-N, recoloring rows, and redrawing the chart. We extend that same pipeline rather than building anything new.

### Decisions locked with the user
- **Group by airline name** (the `flight.airline` field, e.g. "Vueling") — one checkbox per distinct name.
- **All checked on load; unchecking all → empty result** (standard checkbox-filter semantics; falls out naturally from set membership).
- **Each row shows: name + flight count + airline best price, right-aligned** (no logo). "Best price" = cheapest current flight for that airline.
- **List scope = current (latest-snapshot, non-missing) flights only** — consistent with how `max_stops` / `max_duration` bounds are derived today.

### Additional design decisions (planner)
- **Sort order:** airlines listed by **best price ascending** (cheapest carrier first), matching the price-forward UI. Ties broken alphabetically by name.
- **Null/empty airline:** flights with no `airline` value are grouped under a single bucket labeled **"Unknown"** with checkbox value `""`. JS matches on `f.airline || ""` so the bucket behaves like any other.
- **AND semantics:** airline filter intersects with stops + duration (a flight must pass all three). This is automatic — it's just another predicate in `passes()`.

---

## Phase 1 — Server data contract: airline facet + per-row attribute

### Intent
Make the server emit everything the client needs to filter by airline, with zero behavior change to the existing page. The single important decision: the **airline list is built server-side** (distinct name, count, best price, sorted) and passed to the template as a Python list, while the per-flight `airline` value is added to `window.allFlights` so the JS predicate can match it. OUT of scope for this phase: any UI rendering of the list and any JS filtering — rows and chart must look identical to today after this phase.

### Tasks
1.1 In `backend/pages.py` `_build_detail_context`, add `"airline": flight.get("airline")` to each entry appended to `all_flights` (around line 274–281).
1.2 In the same function, after `all_flights` is built, compute an `airlines` facet list from the current non-missing flights: group by `flight.get("airline") or ""`, and for each group produce `{"name": <name or "">, "count": <int>, "best_price": <min price in group>}`.
1.3 Sort `airlines` by `best_price` ascending, then `name` ascending for ties.
1.4 Add `"airlines": airlines` to the returned context dict (a plain Python list — NOT json-dumped; the template iterates it server-side). Keep `all_flights` json-dumped as today.
1.5 Do not change `max_stops` / `max_duration` / `chart_datasets` / `flight_key_colors` computation.
1.6 Add `data-airline="{{ item.flight.airline if item.flight.airline is not none else '' }}"` to the `<tr>` in `frontend/templates/partials/results_table.html` (alongside the existing `data-flight-key` / `data-stops` / `data-duration` attributes).

### Files
- Modify: `backend/pages.py`
- Modify: `frontend/templates/partials/results_table.html`

### What NOT to touch
- `frontend/static/filters.js`, `frontend/static/charts.js`
- `frontend/templates/partials/detail_page.html` (sidebar markup — Phase 2)
- Any chart/color logic, `_assign_chart_colors`, `chart_datasets`, `all_flights` history `data` shape
- `backend/db.py`, `backend/api.py`, `backend/models.py`

### Tests (add to `tests/test_filters.py`)
NON-REGRESSION (must already pass, keep passing):
- `test_all_flights_entry_includes_stops_and_duration` (existing) — proves the existing allFlights contract is intact.
- `test_chart_data_capped_at_top_n_while_all_flights_is_not` (existing).
- `test_row_carries_data_stops_attribute`, `test_row_carries_data_duration_attribute` (existing).

NEW-BEHAVIOR (fail now, pass after):
- `test_all_flights_entry_includes_airline` — an allFlights entry carries the `airline` it was created with.
- `test_airlines_facet_lists_one_entry_per_distinct_airline` — 3 flights across 2 airlines → exactly 2 facet entries. (Inspect via a server-rendered marker; see note.)
- `test_airline_count_reflects_flights_per_airline` — 2 flights of "Vueling" + 1 "Iberia" → Vueling count 2, Iberia count 1.
- `test_airline_best_price_is_min_within_airline` — Vueling at 120 and 90 → best price 90.
- `test_airlines_sorted_by_best_price_ascending` — cheaper airline appears before pricier one in render order.
- `test_row_carries_data_airline_attribute` — row HTML contains `data-airline="Vueling"`.

FAILURE-MODE / EDGE:
- `test_null_airline_grouped_as_unknown_without_crash` — a flight with `airline=None` renders (status 200) and produces an "Unknown"/empty-value group; row renders `data-airline=""`.
- `test_airline_with_ampersand_is_escaped_in_attribute` — airline `"AB & CO"` renders without breaking the attribute (escaped `&amp;` in markup, decodes to the same value).
- `test_airlines_facet_empty_when_no_snapshot` — tracker with no snapshot → no airline rows / empty facet, no crash.
- `test_duplicate_airline_deduped_to_single_entry` — two identical-airline flights → one facet entry, count 2 (dedupe / off-by-one guard).

Note: the airline facet is rendered server-side (not a JS global), so tests assert against the rendered checkbox markup produced in Phase 2. To keep Phase 1 tests grounded without the UI, Phase-1 facet tests assert on `window.allFlights` airline values + counts derived from it; the count/best-price/sort assertions that need the rendered list are written here but **expected to pass only once Phase 2 markup lands**. Label them clearly so the executor runs facet-markup tests after Phase 2. (If preferred, the executor may temporarily expose `airlines` via a hidden global to test Phase 1 in isolation — not required.)

### Verification
```bash
cd /Users/oliversteiner/Documents/code/airfare-monitor
pytest tests/test_filters.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/011-phase-1.md`. Phase 1 is complete when the allFlights/data-airline tests pass and the full suite shows no regressions (was 145 passed / 1 deselected).

---

## Phase 2 — Sidebar UI + client-side airline filtering

### Intent
Render the airline checklist in the sidebar and wire it into the existing filter pipeline so checking/unchecking carriers live-filters both the table and the chart. The important decision: **reuse `applyFilters()` exactly as-is** by adding one predicate and one set of event listeners — no new filtering/coloring/redraw code, because the top-N recompute, row greying, and chart redraw are already centralized there. OUT of scope: persistence (URL/localStorage), logos in the list, and any server changes (done in Phase 1).

### Tasks
2.1 In `frontend/templates/partials/detail_page.html`, add a new `.filter-group` (placed after the duration group, before the Reset button) containing a scrollable airline checklist. For each `a in airlines`: a `<label>` with `<input type="checkbox" class="filter-airline" value="{{ a.name }}" checked>`, the display name (`a.name or "Unknown"`), the count `({{ a.count }})`, and the best price right-aligned (`{{ "%.2f"|format(a.best_price) }} {{ tracker.currency }}`). Wrap in a container with a heading "Airlines".
2.2 Guard the group so it renders only when `airlines` is non-empty (mirrors the `latest_snapshot` guard already wrapping the sidebar).
2.3 Bump the `filters.js` cache-buster (`?v=012` → `?v=013`) on the `<script src>` line; do the same for `charts.js` only if you touch it (you should not).
2.4 In `frontend/static/filters.js` `applyFilters()`: read checked airline checkboxes into a `Set` (`selectedAirlines`); add `airlineOk` to `passes(f)` as `selectedAirlines.has(f.airline || "")`. If there are no airline checkboxes on the page at all (no sidebar), treat airline as always-pass so the function stays backward-compatible.
2.5 In `init()`: attach a `change` listener to every `.filter-airline` checkbox that calls `applyFilters`.
2.6 In the Reset handler: re-check all `.filter-airline` checkboxes before calling `applyFilters`.
2.7 Confirm `htmx:afterSwap` re-init still rebinds airline checkboxes after a "Search Now" / toggle swap (the existing `init()` on `htmx:afterSwap` covers this; verify the new listeners are inside `init`).
2.8 Add minimal CSS in `frontend/static/app.css` for the airline list: a max-height scrollable block and a flex row (name left, price right) for alignment. Match existing `.filter-group` styling.

### Files
- Modify: `frontend/templates/partials/detail_page.html`
- Modify: `frontend/static/filters.js`
- Modify: `frontend/static/app.css`

### What NOT to touch
- `backend/pages.py` (data contract finalized in Phase 1)
- `frontend/static/charts.js` (`renderPriceChart` unchanged)
- Stops / duration controls and their existing JS branches
- `_assign_chart_colors` / color palette (the JS `COLORS` array stays as-is)

### Tests
Server-rendered markup tests (these are the Phase-1 facet tests that need the rendered list — they pass once this phase's template lands):
- `test_sidebar_renders_airline_checkbox_per_airline` — N distinct airlines → N `class="filter-airline"` checkboxes.
- `test_airline_checkbox_checked_by_default` — every airline checkbox has `checked`.
- `test_airline_checkbox_value_is_airline_name` — checkbox `value="Vueling"` present.
- `test_airline_row_shows_count_and_best_price` — rendered list row contains the count and the formatted best price + currency.
- `test_null_airline_renders_unknown_label` — empty-value checkbox renders with visible label "Unknown".
- plus the sort / count / best-price assertions deferred from Phase 1.

NON-REGRESSION:
- Re-run the full `tests/test_filters.py` (stops + duration sidebar tests) — unchanged behavior.

Client-side behavior (greying rows + chart redraw on airline toggle): **no automated coverage** — pytest-only repo, no JS runner — verified via the manual smoke matrix below, consistent with plan 010 (`.agent/reports/010-phase-4.md`).

### Manual smoke matrix (record in `.agent/reports/011-phase-2.md`)
With a tracker that has ≥2 airlines and ≥2 snapshots:
1. All checked → table + chart identical to pre-change. ✓
2. Uncheck one airline → its rows grey out (`.row-filtered`), its chart lines disappear, top-N recolors by remaining cheapest. ✓
3. Uncheck all → empty chart ("No price data yet"), all rows greyed. ✓
4. Re-check all → restored. ✓
5. Combine with stops/duration → intersection (AND) holds. ✓
6. Reset button → all airlines re-checked, stops/duration reset, full view restored. ✓
7. "Search Now" (HTMX swap) → airline checkboxes rebind and still filter. ✓

### Verification
```bash
cd /Users/oliversteiner/Documents/code/airfare-monitor
pytest tests/test_filters.py -v
pytest tests/ -v -k "not slow"
# then manual:
uvicorn backend.main:app --reload   # open a multi-airline tracker, run the smoke matrix
```
Paste full pytest output + the completed smoke matrix into `.agent/reports/011-phase-2.md`. Phase 2 is complete when all facet-markup tests pass, the full suite shows no regressions, and the smoke matrix is all-green.

---

## Handoff notes

- Existing pipeline to extend (read these first):
  - `backend/pages.py` `_build_detail_context` (lines ~178–300) — where `all_flights`, `max_stops`, `max_duration` are built.
  - `frontend/templates/partials/detail_page.html` (lines ~48–98) — sidebar markup + `window.*` globals + script tags.
  - `frontend/static/filters.js` — `applyFilters()` (predicate + top-N recompute + recolor + redraw) and `init()` (listeners, `htmx:afterSwap`).
  - `frontend/templates/partials/results_table.html` — per-row `data-*` attributes.
  - `tests/test_filters.py` — test patterns (`_extract_js_global`, `_price`, `_make_tracker`); add new tests here, do not modify existing ones.
- The airline filter is **client-only and not persisted**, matching the deferred-persistence note for the stops/duration filters in `CLAUDE.md`. When persistence is later added, serialize the airline selection alongside `filterState`.
- Two phases because Phase 1 is fully unit-testable server-side and ships a no-op-to-the-user data contract; Phase 2 is the visible UI + JS wiring verified largely by manual smoke (no JS test runner in this repo).

## Proposed CLAUDE.md addition (apply on approval — show diff first)
Append one bullet to the "Future me notes" filter-sidebar entry: *"Airline filter (plan 011): client-side, groups current non-missing flights by `flight.airline` name (null → 'Unknown'/value `\"\"`), all-checked-by-default with none-checked = empty result, sorted by best price asc. Server emits an `airlines` facet (name/count/best_price) + `airline` on each `window.allFlights` entry + `data-airline` per row; `filters.js` adds one `selectedAirlines` predicate to `passes()`. Not persisted."* Also update the test-suite count line after the new tests land.
