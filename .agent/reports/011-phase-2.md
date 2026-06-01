# Plan 011 — Phase 1+2 end report

## What was built

**Phase 1 (data contract)**
- Added `"airline": flight.get("airline")` to each entry in `all_flights` in `_build_detail_context` (`backend/pages.py`)
- Built `airlines` facet after `all_flights` is assembled: groups by `flight.get("airline") or ""`, computes count and best_price per group, sorts by `(best_price, name)` ascending
- Added `"airlines": airlines` to the returned context dict (plain Python list, not json-dumped)
- Added `data-airline="{{ item.flight.airline if item.flight.airline is not none else '' }}"` to the `<tr>` in `frontend/templates/partials/results_table.html`

**Phase 2 (sidebar UI + JS filtering)**
- Added airline checklist to `frontend/templates/partials/detail_page.html` inside a new `.filter-group` div, guarded by `{% if airlines %}`, placed between duration control and Reset button. Each airline renders a `<label class="airline-row">` with `<input type="checkbox" class="filter-airline" value="{{ a.name }}" checked>`, display name (`a.name or "Unknown"`), count, and best price + currency
- Bumped `filters.js` cache-buster from `?v=012` to `?v=013`
- Updated `frontend/static/filters.js`: reads checked `.filter-airline` checkboxes into a `Set` (`selectedAirlines`); if no airline checkboxes on page, `selectedAirlines` stays `null` (always-pass); added `airlineOk` predicate to `passes()`; added `change` listener to each `.filter-airline` checkbox in `init()`; reset handler re-checks all `.filter-airline` checkboxes before calling `applyFilters`
- Added `.airline-list`, `.airline-row`, `.airline-name`, `.airline-meta` CSS to `frontend/static/app.css`

## Verification output

```
conda run -n base pytest tests/test_filters.py -v
26 passed in 1.12s

conda run -n base pytest tests/ -v -k "not slow"
158 passed, 1 deselected in 2.32s
```

Previous baseline: 145 passed, 1 deselected. 13 new tests added, all passing, no regressions.

## Commit hash

ee32077 — `[phase-1+2] add airline filter to tracker detail sidebar`

## Deviations from plan

- Phases 1 and 2 were implemented in a single session and committed together (one commit). The plan described them as separate phases but both fit cleanly in one pass with no ambiguity between them.
- No temporary `window.airlines` global was needed — Phase 2 template landed immediately so all facet tests could be grounded in rendered markup.

## Manual smoke matrix

Not yet run — requires `uvicorn backend.main:app --reload` with a live multi-airline tracker. Run manually and verify:

1. All checked → table + chart identical to pre-change.
2. Uncheck one airline → rows grey out, chart lines disappear, top-N recolors.
3. Uncheck all → empty chart, all rows greyed.
4. Re-check all → restored.
5. Combine with stops/duration → AND holds.
6. Reset button → all airlines re-checked, stops/duration reset, full view restored.
7. "Search Now" (HTMX swap) → airline checkboxes rebind and still filter.

## Test gaps / new tests

None. All 13 tests were orchestrator-written and pass.

## Follow-ups / noted but not done

- Airline filter state is not persisted (URL/localStorage) — deferred per plan, consistent with stops/duration.
- If `airline` values contain characters that break JSON (unlikely with current data), the existing `json.dumps(all_flights)` handles it via Python's json module.

## Confidence

**certain** — all tests pass, no changes outside plan scope, JS backward-compatibility preserved (no airline checkboxes = no airline filtering).
