# Plan 010 — Tracker-page filter sidebar (stops + duration)

## Context

**Why:** On a tracker's detail page (`/trackers/{id}`) the user wants to narrow the
displayed flights by **number of stops** and **total duration**, without losing sight
of what was filtered out. The need: see only the flights that matter (e.g. "nonstop,
under 8h") while the chart re-focuses on those flights and the rejected ones stay
visible-but-dimmed for reference. Airline filtering is explicitly a **later** feature
(more complex — flight_key/airline-name coupling) and is OUT of scope here.

**Decisions locked with the user:**
- **Mechanism:** *client-side JS*. Sidebar controls re-filter instantly, no server round-trip.
- **Chart behaviour:** *recompute top-N*. When a filter removes a charted flight, the
  next-cheapest **surviving** flight is promoted into the chart with a color. The chart
  always shows up to `top_n` colored lines among the surviving set.
- **Controls:** a **max-stops** `<select>` (Any / Nonstop / ≤1 / ≤2 …) and a **max total
  duration** slider.
- **Filtered rows:** stay in the table but **greyed out**; surviving rows keep the plan-009
  color accent; rows beyond the surviving top-N stay neutral.
- **Persistence:** reset-on-refresh for now, but the user *will* want it. We **build the seam**
  (centralized filter-state object + single `applyFilters()` re-run on every HTMX swap) and
  **defer the storage** (URL/localStorage) to a follow-up plan.

**The key architectural consequence:** "client-side" + "recompute top-N" means the browser
must be able to build a chart line for *any* current flight that a filter promotes — so the
server must ship the **full price history of every current flight**, plus each flight's
`stops`/`duration_min`. Today the server ships history for the top-N only
(`backend/pages.py:224-237`). The server's plan-009 coloring becomes the **initial (no-filter)
render**; JS owns color/chart/row-accent whenever a filter is active and restores the initial
state when filters clear.

---

## What I found (existing system)

- **Data is already present.** Both `get_flight_prices_for_snapshot` (`db.py:233`, `SELECT *
  … ORDER BY price ASC`) and `get_price_history` (`db.py:245`) return `duration_min` (int,
  **nullable**) and `stops` (int) per flight. **No DB or `sources/` change is needed.**
- **Color is server-authoritative (plan 009).** `_assign_chart_colors(flight_keys)`
  (`pages.py:35`) maps key→`CHART_COLORS[i % len]` by list position. `charts.js:18-21` holds an
  identical palette as fallback (`ds.color || colors[i % len]`, `charts.js:27-28`).
- **Coupling to fix first (Phase 1):** color order is currently the *history-first-seen* order
  (`chart_datasets` dict built by iterating `history` ASC, `pages.py:224-237`; keys fed to
  `_assign_chart_colors` at `pages.py:239`). That order is **not replicable client-side** and is
  incidental. To let the JS recompute colors identically, we make the rule deterministic:
  **cheapest survivor → palette[0]** (price-rank order).
- **Chart is client-side**, fed by `window.chartData` (`detail_page.html:65`) and rendered by an
  IIFE in `charts.js`. The table is server-rendered (`results_table.html`); rows already carry
  `data-flight-key` and `row-colored`/`--row-color` (plan 009).
- **HTMX swap:** "Search Now" and pause/resume re-render `#detail-content` via
  `partials/detail_page.html` (`pages.py:269,304`). Scripts in swapped content re-execute, which
  is how the chart redraws. The filter engine must re-init on swap the same way.
- **Layout** is stacked (`.chart-section` then `.results-section`, `app.css:377-402`); there is
  no sidebar yet. The detail page lives inside `#detail-content` (`detail_page.html:1`).
- **Test infra is pytest-only** (no JS test runner). So automated coverage anchors the
  **server data contract**, the **color-rank rule**, and **server-rendered template
  attributes/controls**; the JS filter *behaviour* is verified by **manual smoke** (documented
  in each report). This split is called out per phase.

---

## Architecture of the change

**Phase 1 — deterministic color (refactor).** Build an *ordered* top-key list by price and feed
that to `_assign_chart_colors`; pre-create `chart_datasets` in that order. Cheapest → palette[0].

**Phase 2 — full data contract.** Add `window.allFlights`: one entry per **current non-missing**
flight (not just top-N) with `{flight_key, label, price, stops, duration_min, data:[{x,y}…]}`.
Add `data-stops` / `data-duration` to each table row.

**Phase 3 — reusable chart render.** Refactor `charts.js` to expose
`window.renderPriceChart(datasets)`; the initial load calls it with `window.chartData`. This is
the seam the filter engine calls to redraw.

**Phase 4 — sidebar + filter engine.** Server renders the sidebar controls with data-derived
bounds (max stops, max duration). `filters.js` reads control state into one `filterState`
object, computes survivors from `window.allFlights`, recomputes price-rank top-N + palette
colors, calls `renderPriceChart`, greys filtered rows, recolors survivors, neutralizes the rest.
Re-runs on `htmx:afterSwap`.

**Phase 5 — verify + docs.** Full suite, manual smoke matrix, CLAUDE.md note, persistence-seam note.

**Single source of truth for color rule:** price-rank, palette = `CHART_COLORS`
(`pages.py:29`) mirrored by `charts.js` `colors`. Server applies it on initial render; JS applies
the identical rule on filter change.

---

## Phase 1 — Deterministic price-rank color order (refactor, no new feature)

**Intent:** The chart-line/row colors must be reproducible by client JS, but today they follow
the incidental history-first-seen order. This phase makes the rule *cheapest-survivor →
palette[0]* so server-initial and JS-recomputed colors agree. The single design decision: order
the keys fed to `_assign_chart_colors` by **price ascending** (which `flights_with_delta[:top_n]`
already is) instead of by `chart_datasets` insertion order. OUT of scope: any filter UI, any new
data, any JS change.

### Tasks
1.1 In `_build_detail_context` (`pages.py:221-241`), replace the `latest_top_keys` **set** with an
    **ordered list** `ordered_top_keys` = `[f["flight"]["flight_key"] for f in
    flights_with_delta[:top_n] if delta.type != "missing"]` (price-asc, dedup-safe).
1.2 Call `flight_key_colors = _assign_chart_colors(ordered_top_keys)` from that ordered list.
1.3 Pre-create `chart_datasets` as an ordered dict keyed in `ordered_top_keys` order, each with
    `label`, empty `data`, and `color` from the map; derive `label` from the flight
    (`flight_number` → `airline` → key) instead of from a history row.
1.4 Iterate `history` only to **append points** to existing datasets (`if key in chart_datasets`).
1.5 Keep the returned context keys identical (`chart_datasets` JSON, `flight_key_colors`).
1.6 Run the color tests; confirm the NEW rank test fails before and passes after, and all 009
    color tests stay green.

### Files
- Modify: `backend/pages.py`

### Design notes / risks
- 009 single-flight tests still hold (cheapest = only = palette[0]).
- Dataset *order* in the emitted JSON changes from chronological to price-rank — verify the
  `'"label": "6201"'` anchor still appears (it does; reordering doesn't drop it).

### What NOT to touch
- `_assign_chart_colors` itself, `CHART_COLORS`, `charts.js`, any template, `db.py`.

### Success criteria (tests that must pass)
- NEW-BEHAVIOR: `tests/test_chart_data.py::test_color_assigned_by_price_rank_not_history_order`
- NON-REGRESSION (009, must stay green):
  - `tests/test_chart_data.py::test_chart_dataset_color_is_first_palette_color_for_single_flight`
  - `tests/test_chart_data.py::test_chart_dataset_includes_color_field`
  - `tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n`
  - `tests/test_chart_colors.py` (full file)
  - `tests/test_pages.py::test_charted_row_carries_its_chart_color`

### Verification
```bash
pytest tests/test_chart_data.py tests/test_chart_colors.py tests/test_pages.py -v
```
Paste full output into `.agent/reports/010-phase-1.md`.

---

## Phase 2 — Ship full per-flight data to the client

**Intent:** "Recompute top-N" client-side is impossible unless the browser holds the price
history + filter attributes of *every* current flight, since a filter can promote a flight that
wasn't originally charted. This phase adds that data contract — `window.allFlights` plus
`data-stops`/`data-duration` on rows — with **no UI yet**. Single decision: derive `allFlights`
from the already-fetched `history` (grouped by current non-missing keys) so no new DB query is
added. OUT of scope: sidebar, `filters.js`, chart re-render.

### Tasks
2.1 In `_build_detail_context`, build `all_flights` = list over **current non-missing** flights
    (all of them, not `top_n`): `{flight_key, label, price, stops, duration_min, data:[{x,y}…]}`,
    where `data` is that key's full series from `history` (same `{x: searched_at→T, y: price}`
    shape as `chart_datasets`).
2.2 Add `"all_flights": json.dumps(all_flights)` to the returned context.
2.3 Emit `<script>window.allFlights = {{ all_flights | safe }};</script>` in
    `partials/detail_page.html`, next to the existing `window.chartData` line (`:65`).
2.4 In `results_table.html`, add `data-stops="{{ item.flight.stops }}"` and
    `data-duration="{{ item.flight.duration_min if item.flight.duration_min is not none else '' }}"`
    to each `<tr>` (empty string when duration is null).
2.5 Confirm `chart_datasets` / `flight_key_colors` are unchanged (still top-N only).
2.6 Run the new data-contract tests + full suite.

### Files
- Modify: `backend/pages.py`, `frontend/templates/partials/detail_page.html`,
  `frontend/templates/partials/results_table.html`

### Design notes / risks
- `all_flights` includes flights beyond `top_n` (that's the point) and **excludes** "missing"
  rows (they can never be promoted into the chart).
- Null `duration_min` → emitted as empty `data-duration` and `duration_min: null` in JSON; the
  filter engine treats null as "passes the max-duration filter" (Phase 4 decision).

### What NOT to touch
- `charts.js`, `app.css`, chart-dataset/color logic, `db.py`.

### Success criteria (tests that must pass)
- NEW-BEHAVIOR:
  - `tests/test_filters.py::test_all_flights_includes_flight_beyond_top_n`
  - `tests/test_filters.py::test_all_flights_entry_includes_stops_and_duration`
  - `tests/test_filters.py::test_all_flights_includes_full_history_series_per_flight`
  - `tests/test_filters.py::test_row_carries_data_stops_attribute`
  - `tests/test_filters.py::test_row_carries_data_duration_attribute`
- FAILURE-MODE / EDGE:
  - `tests/test_filters.py::test_all_flights_is_empty_array_when_no_snapshot`
  - `tests/test_filters.py::test_row_with_null_duration_renders_empty_data_duration`
- NON-REGRESSION:
  - `tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n`
  - `tests/test_pages.py::test_detail_page_contains_results_table_when_snapshot_exists`

### Verification
```bash
pytest tests/test_filters.py tests/test_chart_data.py tests/test_pages.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/010-phase-2.md`.

---

## Phase 3 — Reusable chart render function

**Intent:** The filter engine needs to redraw the chart with a recomputed dataset list, but the
Chart.js config lives inside an anonymous IIFE in `charts.js`. This phase extracts a single
`window.renderPriceChart(datasets)` so both the initial load and the filter engine share one
render path (no duplicated axis/tooltip config). Single decision: keep behaviour identical for
the initial load (`renderPriceChart(window.chartData)`), so this is a pure refactor. OUT of
scope: any filter logic or sidebar.

### Tasks
3.1 In `charts.js`, move the dataset-prep + `new Chart(...)` body into
    `window.renderPriceChart(datasets)`; keep the canvas lookup, existing-chart `destroy()`, and
    the "No price data yet" empty path inside it.
3.2 Preserve the `ds.color || colors[i % colors.length]` fallback and all axis/tooltip callbacks
    verbatim.
3.3 At the bottom, call `renderPriceChart(window.chartData || [])` to retain current behaviour.
3.4 Ensure re-invocation safely destroys the prior chart (already does via `Chart.getChart`).
3.5 Manual smoke: load a tracker with history — chart renders exactly as before; "Search Now"
    swap still redraws.

### Files
- Modify: `frontend/static/charts.js`

### Design notes / risks
- No automated JS test harness exists; coverage here is the existing page test (canvas present)
  plus manual smoke. Do NOT change palette, axis, or tooltip behaviour.

### What NOT to touch
- `pages.py`, templates, `app.css`, the palette values.

### Success criteria (tests that must pass)
- NON-REGRESSION:
  - `tests/test_pages.py::test_detail_page_contains_chart_canvas_when_snapshot_exists`
  - `tests/ -k "not slow"` stays green (no regressions).
- Manual smoke (recorded in report): initial chart + post-Search-Now redraw unchanged.

### Verification
```bash
pytest tests/ -v -k "not slow"
```
Paste full output + manual-smoke note into `.agent/reports/010-phase-3.md`.

---

## Phase 4 — Sidebar UI + client-side filter engine

**Intent:** Deliver the feature. Server renders an inert-but-correct sidebar (controls bounded by
the data); `filters.js` makes it live — recomputing survivors, price-rank top-N, palette colors,
chart, and row styling on every change, and re-running after each HTMX swap. Single decision:
**filter state lives in one `filterState` object behind one `applyFilters()`** so future
persistence is a thin save/load, not a rewrite. OUT of scope: URL/localStorage persistence,
airline filter.

### Tasks
4.1 Server: in `_build_detail_context`, compute control bounds from current non-missing flights —
    `max_stops` (max `stops`) and `max_duration` (max non-null `duration_min`, default 0/None when
    absent) — and add to context.
4.2 Template: wrap chart+results in a `.detail-layout` flex with a `.filter-sidebar` (in
    `detail_page.html`, inside `#detail-content` so it resets on swap). Sidebar contains a
    **max-stops `<select>`** (Any + one option per 0…`max_stops`) and a **max-duration range
    slider** (`min=0`, `max=max_duration`, default = `max_duration` = "show all") with a live
    value label, plus a "Reset" control.
4.3 CSS: append `.detail-layout`, `.filter-sidebar`, `.row-filtered` rules to `app.css` (do NOT
    edit existing rules — file has known duplicate-rule debt). `.row-filtered` = dimmed + no
    accent (grey wins over `row-colored`); responsive: sidebar stacks above on narrow screens.
4.4 New `frontend/static/filters.js`: a `filterState` object + `applyFilters()` that
    (a) reads stops/duration from controls, (b) filters `window.allFlights` (stops ≤ max;
    duration ≤ max OR duration null → keep), (c) sorts survivors by price asc, takes `top_n`,
    assigns `CHART_COLORS[i]`, (d) calls `window.renderPriceChart(survivingTopN)`, (e) for each
    table row by `data-flight-key`: filtered → add `.row-filtered`, clear accent; surviving-top-N
    → set `--row-color` + `.row-colored`; else neutral.
4.5 Read `top_n` and palette into `filters.js` (emit `window.chartTopN` and reuse the JS palette;
    keep palette identical to `CHART_COLORS`).
4.6 Bind `change`/`input` listeners; **re-run `applyFilters()` on `htmx:afterSwap`** (and on
    initial load) so swaps re-init cleanly. Include `filters.js` after `charts.js` in
    `detail_page.html`.
4.7 Handle edge cases in JS: all flights filtered out → `renderPriceChart([])` shows "No price
    data yet", every row `.row-filtered`; single flight; slider at max = no-op (matches initial).
4.8 Run server-side sidebar tests + full suite; perform the manual smoke matrix.

### Files
- Modify: `backend/pages.py`, `frontend/templates/partials/detail_page.html`,
  `frontend/static/app.css`
- Create: `frontend/static/filters.js`

### Design notes / risks
- **Null duration passes the duration filter** (we can't prove an unknown value violates a max);
  documented + tested. Revisit if the user prefers to hide unknowns.
- **Color identity shifts between filtered/unfiltered views** — inherent to "recompute top-N".
  Within any single view colors are consistent (price-rank). On reset, state returns to the
  server-initial render (slider at max + Any stops reproduce the same price-rank top-N).
- Sidebar inside `#detail-content` → resets on Search Now (matches "reset on refresh"); the
  `htmx:afterSwap` re-bind is what makes the fresh controls live again.
- **Persistence seam:** all mutable state is in `filterState`; persistence later = serialize it to
  URL/localStorage on change and hydrate before the first `applyFilters()`.

### What NOT to touch
- `db.py`, `sources/`, `charts.js` render internals (only call `renderPriceChart`), existing CSS
  rules, `price_badge.html`, the airline-logo macro.

### Success criteria (tests that must pass)
- NEW-BEHAVIOR (server-rendered, automatable):
  - `tests/test_filters.py::test_detail_page_renders_filter_sidebar`
  - `tests/test_filters.py::test_duration_slider_max_equals_longest_flight`
  - `tests/test_filters.py::test_stops_select_max_option_equals_most_stops`
- FAILURE-MODE / EDGE (server-rendered):
  - `tests/test_filters.py::test_sidebar_renders_with_single_flight`
  - `tests/test_filters.py::test_duration_slider_max_is_zero_when_all_durations_null`
- NON-REGRESSION:
  - `tests/test_pages.py::test_detail_page_contains_results_table_when_snapshot_exists`
  - `tests/test_pages.py::test_charted_row_carries_its_chart_color` (initial render unchanged)
- Manual smoke (recorded in report) — see Verification matrix.

### Verification
```bash
pytest tests/test_filters.py tests/test_pages.py -v
pytest tests/ -v -k "not slow"
# then: uvicorn backend.main:app --reload
```
Manual smoke matrix to paste into `.agent/reports/010-phase-4.md`:
1. Open a tracker with several flights → sidebar present; all rows colored/neutral as before.
2. Lower max-stops to Nonstop → 1-stop+ rows grey out; chart drops their lines; a previously
   uncharted nonstop flight gets promoted with a color; its row accent matches the new line.
3. Drag duration slider down → long flights grey; chart + colors recompute consistently.
4. Set both filters to exclude everything → chart shows "No price data yet"; all rows grey.
5. Reset → identical to initial server render (colors + lines).
6. Click "Search Now" → controls reset, chart redraws, filters re-applicable.

---

## Phase 5 — End-to-end verification + docs

**Intent:** Prove the whole feature holds together and capture the conventions for the next
session (especially the persistence seam the user signalled they'll want). OUT of scope: any new
behaviour.

### Tasks
5.1 `pytest tests/ -v -k "not slow"` — 0 failures; confirm baseline + new tests.
5.2 Re-run the Phase 4 manual smoke matrix end-to-end; capture rendered `<tr>` markup and/or a
    screenshot.
5.3 Confirm colors/lines persist correctly across an HTMX "Search Now" swap.
5.4 Add the CLAUDE.md "Future me" note (below) + the new `frontend/static/filters.js` to the
    project structure list. Show before applying.
5.5 Record an explicit "persistence is the deferred next step; seam is `filterState` +
    `applyFilters()` re-run on `htmx:afterSwap`" note in the report.

### Files
- Modify: `CLAUDE.md`

### Verification
```bash
pytest tests/ -v -k "not slow"
```
Paste full output + smoke notes into `.agent/reports/010-phase-5.md`.

---

## Test specifications

**NON-REGRESSION** pass against current code first (anchors). **NEW-BEHAVIOR / FAILURE-MODE**
must fail (for the right reason — a real assertion) before implementation, pass after.
JS-internal behaviour has **no automated test** (pytest-only repo) and is covered by the manual
smoke matrix; automated tests target the server data contract, the color rule, and
server-rendered markup.

### `tests/test_chart_data.py` (addition — Phase 1)
- NEW: `test_color_assigned_by_price_rank_not_history_order` — snapshot 1 has flight **B** only
  (so B is first-seen in history); snapshot 2 has cheap **A** + dearer **B**. GET `/trackers/1`;
  assert the chart JSON assigns `#4a90d9` to **A** (cheapest) and `#e67e22` to **B**. Fails
  pre-refactor (history order → B blue), passes after.

### `tests/test_filters.py` (new file — Phases 2 & 4)
DB fixtures via existing `create_tracker` / `create_snapshot` / `insert_flight_prices`; assert on
`response.text` of GET `/trackers/{id}`.

Phase 2 (data contract):
- NEW: `test_all_flights_includes_flight_beyond_top_n` — insert `top_n + 1` flights at distinct
  prices; assert the (top_n+1)-th flight's `flight_key` appears in the `window.allFlights` JSON
  **but not** in `window.chartData`. *(off-by-one boundary at top_n.)*
- NEW: `test_all_flights_entry_includes_stops_and_duration` — assert a flight's `stops` and
  `duration_min` values appear in the `allFlights` JSON.
- NEW: `test_all_flights_includes_full_history_series_per_flight` — two snapshots for one flight;
  assert its `allFlights` entry has two `{x,y}` points.
- NEW: `test_row_carries_data_stops_attribute` — assert `data-stops="0"` on the nonstop row.
- NEW: `test_row_carries_data_duration_attribute` — assert `data-duration="<min>"` present.
- FAILURE/EDGE: `test_all_flights_is_empty_array_when_no_snapshot` — tracker with no snapshot;
  assert `window.allFlights = []` (or `[]` present, no rows). *(empty input.)*
- FAILURE/EDGE: `test_row_with_null_duration_renders_empty_data_duration` — flight with
  `duration_min=None`; assert `data-duration=""` and no template crash. *(null.)*

Phase 4 (sidebar markup, server-rendered):
- NEW: `test_detail_page_renders_filter_sidebar` — assert `class="filter-sidebar"` present when a
  snapshot exists.
- NEW: `test_duration_slider_max_equals_longest_flight` — flights with durations e.g. 120 & 540;
  assert the slider `max="540"`. *(max value.)*
- NEW: `test_stops_select_max_option_equals_most_stops` — flights with stops 0,1,2; assert an
  option for `2` exists. *(max value.)*
- EDGE: `test_sidebar_renders_with_single_flight` — one flight; sidebar still renders. *(single.)*
- EDGE: `test_duration_slider_max_is_zero_when_all_durations_null` — all `duration_min=None`;
  assert slider `max="0"` and no crash. *(null/zero boundary.)*

### `tests/test_pages.py` (additions — Phases 1-4 anchors)
- NON-REGRESSION (existing, must stay green): `test_charted_row_carries_its_chart_color`,
  `test_detail_page_contains_results_table_when_snapshot_exists`,
  `test_detail_page_contains_chart_canvas_when_snapshot_exists`.

### Deliverables (files)
- Plan: `.agent/plans/010-tracker-filter-sidebar.md` (this file, persisted on approval)
- New test file: `tests/test_filters.py`
- Test additions: `tests/test_chart_data.py`
- New app file (impl): `frontend/static/filters.js`
- Reports: `.agent/reports/010-phase-{1,2,3,4,5}.md`

---

## Proposed CLAUDE.md addition (Phase 5 — show before applying)

Add under "Future me notes":

> - **Tracker filter sidebar (stops + duration)**: client-side. Server ships `window.allFlights`
>   (full history + `stops`/`duration_min` for every current non-missing flight) and an inert
>   sidebar with data-bounded controls; `frontend/static/filters.js` makes it live. On each change
>   (and `htmx:afterSwap`) `applyFilters()` filters `allFlights`, recomputes the price-rank top-N,
>   assigns `CHART_COLORS` by rank (cheapest = palette[0]), redraws via `window.renderPriceChart`
>   (extracted from `charts.js`), greys filtered rows (`.row-filtered`, wins over `.row-colored`),
>   and recolors survivors. Color is **price-rank** now (was history-order) so server-initial and
>   JS-recomputed colors agree. Null `duration_min` passes the duration filter. Filter state lives
>   in one `filterState` object — persistence (URL/localStorage) is the deferred next step, wired
>   by serializing that object. Airline filter is also future.

Also add `frontend/static/filters.js` to the project-structure tree.

---

## Handoff notes
- Core wiring: `backend/pages.py` `_build_detail_context` (`:167-254`) — color order (P1),
  `all_flights` + bounds (P2/P4).
- Data emission + sidebar: `frontend/templates/partials/detail_page.html` (`window.chartData` at
  `:65`, scripts `:65-67`); rows in `frontend/templates/partials/results_table.html`.
- Chart: `frontend/static/charts.js` — extract `renderPriceChart` (P3), palette `:18-21`.
- Engine: new `frontend/static/filters.js` (P4); CSS appended to `frontend/static/app.css`.
- Color rule is **price-rank**, mirrored between `CHART_COLORS` (`pages.py:29`) and the JS palette.
- Plan 009 tests are the non-regression spine — keep them green at every phase.
- Full-suite baseline: `pytest tests/ -v -k "not slow"` → 131 passed, 1 deselected.
