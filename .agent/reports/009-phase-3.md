# 009 Phase 3 Report — Color the table rows (left accent border)

## What was built

- `results_table.html`: inside the row loop, added `{% set row_color = (flight_key_colors or {}).get(item.flight.flight_key) %}`. Updated `<tr>` to carry `data-flight-key`, `row-colored` class (conditional), and `style="--row-color: {{ row_color }}"` (conditional). Existing `row-missing` class logic preserved.
- `app.css`: appended `.results-table tr.row-colored td:first-child { box-shadow: inset 4px 0 0 var(--row-color); }` — uses inset box-shadow to avoid border-collapse layout shift.

## Verification output

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
asyncio: mode=Mode.AUTO

collected 131 items / 1 deselected / 130 selected (full suite)

[all 130 selected tests PASSED]

131 passed, 1 deselected in 1.47s
```

## Commit

`17716c9` — `[phase-3.1] color results-table rows with left accent border matching chart line`

## Deviations

Used `(flight_key_colors or {}).get(...)` as the plan's Design notes recommended, to guard against the variable being undefined in non-detail render paths.

## Confidence

certain
