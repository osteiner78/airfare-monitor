# Plan 009 — Colorize results-table rows to match chart line colors

## Context

The detail page shows a price-history **chart** (top) and a **results table** (below). Each chart line is one flight (`flight_key`); each table row is one flight. The request: give each table row a colored accent matching its chart line, so the eye can connect "this line = this row."

Today the chart assigns color by **dataset array index** (`charts.js:27`, `colors[i % len]`), and the table has no notion of color or even `flight_key` on its rows. The dataset order is price-history-first-seen (`get_price_history` → `ORDER BY searched_at ASC`), while the table is `price ASC` (`db.py:238`) — so any index-based row coloring only *looks* aligned by coincidence (the cheapest N happen to be charted and top-of-table). It will drift the moment the planned **duration/stops filter** removes a cheaper flight. The fix must key color on `flight_key`, not row position.

### Decisions locked with the user
- **Visual**: a ~4px **left accent border** on each row that corresponds to a chart line.
- **Uncharted rows** (flights beyond the charted top-N, and "missing" rows from a previous snapshot): **no color** — render exactly as today.
- **Single source of truth**: colors are **assigned on the server** by a pure `flight_key → color` helper. It feeds both (a) the chart datasets (new `color` field consumed by `charts.js`) and (b) a `flight_key_colors` map passed to the results table. The palette becomes server-authoritative; `charts.js` keeps its palette only as a fallback.

### Why a chart line ⇄ row can be absent
The chart shows only `latest_top_keys` = the top-N cheapest **current** flights (`pages.py:192`). The table shows all current flights plus "missing" rows. Only flights in `latest_top_keys` get a chart line, hence only those rows get a color. This is intentional (the user chose "no color" for the rest).

---

## Architecture of the change

**Pure color helper (the testable seam)** — new in `backend/pages.py`:

```python
CHART_COLORS = [
    "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
    "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
]

def _assign_chart_colors(flight_keys: list[str]) -> dict[str, str]:
    """Map each flight_key to a palette color by position, cycling the palette.
    Order matches the chart dataset order so chart line and table row agree."""
    return {key: CHART_COLORS[i % len(CHART_COLORS)] for i, key in enumerate(flight_keys)}
```

This palette is the same 10 colors currently in `charts.js:18-21`, moved server-side.

**Context wiring** — in `_build_detail_context` (`pages.py:137`), after `chart_datasets` is built (dict keyed by `flight_key`, in chart order):

```python
flight_key_colors = _assign_chart_colors(list(chart_datasets.keys()))
for key, entry in chart_datasets.items():
    entry["color"] = flight_key_colors[key]
...
return {
    ...,
    "chart_datasets": json.dumps(list(chart_datasets.values())),  # now each entry has "color"
    "flight_key_colors": flight_key_colors,                       # NEW
}
```

Because both outputs derive from the *same* dict-key order, chart line color and table row color are guaranteed identical for a given `flight_key` regardless of table sort order.

**Chart consumption** — `charts.js` uses the server color, falling back to its index palette so the no-data / missing-color paths stay safe:

```javascript
ds.borderColor = ds.color || colors[i % colors.length];
ds.backgroundColor = (ds.color || colors[i % colors.length]) + "20";
```

**Table rendering** — `results_table.html` looks up the row's color and applies the left border only when present:

```jinja
{% set row_color = flight_key_colors.get(item.flight.flight_key) %}
<tr data-flight-key="{{ item.flight.flight_key }}"
    class="{% if item.delta and item.delta.type == 'missing' %}row-missing{% endif %}{% if row_color %} row-colored{% endif %}"
    {% if row_color %}style="--row-color: {{ row_color }}"{% endif %}>
```

CSS uses an inset box-shadow (renders reliably under `border-collapse`, no layout shift):

```css
.results-table tr.row-colored td:first-child { box-shadow: inset 4px 0 0 var(--row-color); }
```

---

## Phase 1 — Pure color-assignment helper

Add the seam. No behavior change yet (helper not wired in).

### Tasks
1.1 Add the `CHART_COLORS` palette constant to `backend/pages.py` (same 10 hex values as `charts.js:18-21`).
1.2 Add `_assign_chart_colors(flight_keys: list[str]) -> dict[str, str]` as shown above.
1.3 Do NOT yet call it from `_build_detail_context` or change any template/JS.
1.4 Run the helper edge-case tests; confirm NEW tests fail before 1.1–1.2 and pass after.

### Files
- Modify: `backend/pages.py`

### Design notes / risks
- Cycling (`i % len`) is intentional: >10 charted flights reuse colors. Acceptable (chart `top_n` default is 5).
- Keep the palette identical to the JS list so the fallback path in `charts.js` is visually consistent.

### What NOT to touch
- `_build_detail_context`, `_split_timestamps`, `_format_date`, route handlers.
- `charts.js`, any template, `db.py`.

### Success criteria (tests that must pass)
- `tests/test_chart_colors.py::test_returns_empty_dict_for_empty_key_list`
- `tests/test_chart_colors.py::test_single_key_gets_first_palette_color`
- `tests/test_chart_colors.py::test_distinct_colors_for_keys_within_palette_size`
- `tests/test_chart_colors.py::test_assigns_colors_in_positional_order`
- `tests/test_chart_colors.py::test_palette_cycles_when_more_keys_than_colors`
- `tests/test_chart_colors.py::test_eleventh_key_reuses_first_color`
- `tests/test_chart_colors.py::test_handles_unicode_and_pipe_delimited_keys`
- `tests/test_chart_colors.py::test_duplicate_keys_collapse_to_single_entry`

### Verification
```bash
pytest tests/test_chart_colors.py -v
```
Paste full output into `.agent/reports/009-phase-1.md`.

---

## Phase 2 — Wire colors into chart datasets, context, and charts.js

Make the chart use server-assigned colors and expose `flight_key_colors` for the table.

### Tasks
2.1 In `_build_detail_context` (`pages.py`), after the `chart_datasets` loop, call `_assign_chart_colors(list(chart_datasets.keys()))`.
2.2 Set `entry["color"]` on each `chart_datasets` value from that map.
2.3 Add `"flight_key_colors": flight_key_colors` to the returned context dict.
2.4 In `frontend/static/charts.js`, change `ds.borderColor`/`ds.backgroundColor` to prefer `ds.color` with the existing palette as fallback (keep the no-data path at `charts.js:8` unchanged).
2.5 Confirm the emitted `window.chartData` JSON now contains a `color` field per dataset.
2.6 Run chart-data + page tests; confirm the existing label anchor stays green and the new color-in-JSON test passes.

### Files
- Modify: `backend/pages.py`
- Modify: `frontend/static/charts.js`

### Design notes / risks
- Adding `"color"` to each dataset must not disturb the existing assertion `'"label": "6201"'` (`test_chart_data.py:60`) — `json.dumps` still includes `label`. Verify.
- `flight_key_colors` is added to context but only *consumed* in Phase 3; harmless until then.

### What NOT to touch
- `results_table.html` (Phase 3), `app.css` (Phase 3).
- The chart axis/tooltip config in `charts.js` (lines 34-85).
- `db.py`.

### Success criteria (tests that must pass)
- NEW: `tests/test_chart_data.py::test_chart_dataset_includes_color_field`
- NEW: `tests/test_chart_data.py::test_chart_dataset_color_is_first_palette_color_for_single_flight`
- NON-REGRESSION: `tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n` (existing — `'"label": "6201"'` must still appear)
- NON-REGRESSION: `tests/test_pages.py::test_detail_page_contains_chart_canvas_when_snapshot_exists` (existing)

### Verification
```bash
pytest tests/test_chart_data.py tests/test_pages.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/009-phase-2.md`.

---

## Phase 3 — Color the table rows (left accent border)

Render the left border on charted rows; leave the rest neutral.

### Tasks
3.1 In `frontend/templates/partials/results_table.html`, add `{% set row_color = flight_key_colors.get(item.flight.flight_key) %}` inside the row loop.
3.2 Add `data-flight-key="{{ item.flight.flight_key }}"` to the `<tr>` (stable hook; also useful for the future filter feature).
3.3 Add `row-colored` to the `<tr>` class and `style="--row-color: {{ row_color }}"` only when `row_color` is truthy; preserve the existing `row-missing` class logic (`results_table.html:18`).
3.4 Add the CSS rule `.results-table tr.row-colored td:first-child { box-shadow: inset 4px 0 0 var(--row-color); }` to `frontend/static/app.css`. Append cleanly; do NOT edit or duplicate existing rules (the file has known duplicate-rule debt).
3.5 Confirm `row-missing` rows that are NOT charted get no `--row-color` and no `row-colored` class.
3.6 Run page tests; confirm NEW tests fail before 3.1–3.3 and pass after, and existing results-table tests stay green.

### Files
- Modify: `frontend/templates/partials/results_table.html`
- Modify: `frontend/static/app.css`

### Design notes / risks
- `flight_key_colors` may be absent in non-detail render paths that reuse `results_table.html`? It is only included via `partials/detail_page.html` (the only includer). Use `flight_key_colors.get(...)` defensively; if the var is undefined Jinja raises — guard with `{% set row_color = (flight_key_colors or {}).get(item.flight.flight_key) %}` to be safe.
- `box-shadow inset` chosen over `border-left` because `border-collapse` on `.results-table` can swallow `<tr>` borders and `border` on a cell shifts column width. Box-shadow does neither.
- HTMX swaps `#detail-content` wholesale, so colors re-render correctly after "Search Now".

### What NOT to touch
- Other cells/columns; `price_badge.html`; the airline-logo cell from plan 008.
- `pages.py`, `db.py`, `charts.js`.
- Existing CSS rules (`.row-missing`, `.price-cell`, etc.).

### Success criteria (tests that must pass)
- NEW: `tests/test_pages.py::test_charted_row_carries_its_chart_color`
- NEW: `tests/test_pages.py::test_charted_row_has_flight_key_data_attribute`
- FAILURE-MODE: `tests/test_pages.py::test_missing_row_has_no_row_color`
- NON-REGRESSION: `tests/test_pages.py::test_detail_page_contains_results_table_when_snapshot_exists` (existing)

### Verification
```bash
pytest tests/test_pages.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/009-phase-3.md`.

---

## Phase 4 — End-to-end verification + docs

### Tasks
4.1 Run the full suite: `pytest tests/ -v -k "not slow"` — confirm baseline (100) + new tests, 0 failures.
4.2 Manual smoke: `uvicorn backend.main:app --reload`, open a tracker with history; confirm each row's left bar color **equals** its chart line color, and that rows below the charted top-N (and missing rows) have no bar.
4.3 Confirm colors persist correctly after clicking "Search Now" (HTMX swap).
4.4 Add the CLAUDE.md "Future me" note (below).
4.5 Paste a screenshot or the rendered `<tr ...>` markup into the report.

### Files
- Modify: `CLAUDE.md` (one note)

### What NOT to touch
- Anything else; verification + docs only.

### Verification
```bash
pytest tests/ -v -k "not slow"
```
Paste full output + manual-smoke notes into `.agent/reports/009-phase-4.md`.

---

## Test specifications

**NEW-BEHAVIOR** / **FAILURE-MODE** tests must fail (for the right reason) before implementation; **NON-REGRESSION** tests must pass against current code first.

### `tests/test_chart_colors.py` (new file — Phase 1)
Direct unit tests of `backend.pages._assign_chart_colors` — a pure, documented helper that is the single source of truth for color. (Not a private intermediate value: it has a defined input/output contract used by two render paths.)

NEW-BEHAVIOR:
- `test_single_key_gets_first_palette_color` — `["k1"]` → `{"k1": "#4a90d9"}`
- `test_distinct_colors_for_keys_within_palette_size` — 3 keys → 3 distinct palette colors
- `test_assigns_colors_in_positional_order` — `["a","b"]` → `a`=`CHART_COLORS[0]`, `b`=`CHART_COLORS[1]`
- `test_handles_unicode_and_pipe_delimited_keys` — `["test|VY|6201|2026-01-01T00:00:00", "✈|x|1|t"]` used verbatim as dict keys, each gets a palette color

FAILURE-MODE (edge matrix: empty, boundary/cycle, off-by-one, duplicates, unicode):
- `test_returns_empty_dict_for_empty_key_list` — `[]` → `{}`
- `test_palette_cycles_when_more_keys_than_colors` — 12 keys → all map to a palette color (every value ∈ `CHART_COLORS`)
- `test_eleventh_key_reuses_first_color` — 11 keys → key[10] maps to `CHART_COLORS[0]` (off-by-one on the 10-color cycle)
- `test_duplicate_keys_collapse_to_single_entry` — `["a","a"]` → dict has one `"a"` (value = last index, `CHART_COLORS[1]`); pins dedup behavior

### `tests/test_chart_data.py` (additions — Phase 2)
Assert on rendered HTML / emitted `window.chartData` JSON; DB fixtures via existing `create_snapshot` + `insert_flight_prices`.

NEW-BEHAVIOR:
- `test_chart_dataset_includes_color_field` — one charted flight; GET `/trackers/1`; assert `'"color":'` (or `'"color": '`) present in `response.text`.
- `test_chart_dataset_color_is_first_palette_color_for_single_flight` — one flight; assert `"#4a90d9"` present in the chart data JSON.

NON-REGRESSION:
- `test_chart_datasets_limited_to_sticky_top_n` (existing) — `'"label": "6201"'` still present.

### `tests/test_pages.py` (additions — Phase 3)
NEW-BEHAVIOR:
- `test_charted_row_carries_its_chart_color` — insert one flight `flight_key="test|VY|6201|2026-01-01T00:00:00"`; GET `/trackers/1`; assert `--row-color: #4a90d9` appears in `response.text`.
- `test_charted_row_has_flight_key_data_attribute` — same fixture; assert `data-flight-key="test|VY|6201|2026-01-01T00:00:00"` in `response.text`.

FAILURE-MODE:
- `test_missing_row_has_no_row_color` — snapshot 1 with flightA, snapshot 2 with flightB only (flightA becomes "missing"); GET `/trackers/1`; assert the `row-missing` row for flightA does NOT carry `--row-color` (assert flightA's color hex is not applied to its row / `row-colored` not on the missing row). Pins that uncharted rows stay neutral.

NON-REGRESSION:
- `test_detail_page_contains_results_table_when_snapshot_exists` (existing) — stays green.

### Deliverables (files)
- Plan: `.agent/plans/009-row-color-chart-match.md`
- New test file: `tests/test_chart_colors.py`
- Test additions: `tests/test_chart_data.py`, `tests/test_pages.py`
- Reports: `.agent/reports/009-phase-{1,2,3,4}.md`

---

## Proposed CLAUDE.md addition (Phase 4 — show before applying)

Add under "Future me notes":

> - **Row/chart color sync**: results-table rows get a left accent border matching their chart line. Colors are assigned server-side by `_assign_chart_colors(flight_keys)` in `pages.py` (palette `CHART_COLORS`, cycled by position). The same map feeds chart datasets (`color` field, consumed by `charts.js` with the JS palette as fallback) and the table via `flight_key_colors` in the detail context. Only charted flights (`latest_top_keys`, the top-N cheapest current flights) are colored; uncharted and "missing" rows stay neutral. Rows carry `data-flight-key` (also a hook for the planned duration/stops filter).

---

## Handoff notes
- Core logic: `backend/pages.py` — `CHART_COLORS`, `_assign_chart_colors`, and the `_build_detail_context` wiring (`pages.py:137`, chart loop `:193-207`).
- Chart consumption: `frontend/static/charts.js:23-32` (palette currently `:18-21`).
- Table: `frontend/templates/partials/results_table.html` (row at `:18`), included only by `partials/detail_page.html` (emits `window.chartData` at `:65`).
- Color mapping is by `flight_key`, NOT row index — this is what survives the upcoming duration/stops filter. `data-flight-key` on each row is deliberately added now to serve that future feature.
- Ordering facts: chart dataset order = `get_price_history` (`searched_at ASC`, `db.py:245`); table order = `get_flight_prices_for_snapshot` (`price ASC`, `db.py:238`). They differ — never align color by index.
- Full suite baseline: `pytest tests/ -v -k "not slow"` → 100 passed, 1 deselected.
