# Phase 3 — Reusable chart render function

## What was built

Refactored `charts.js`: the dataset-prep + `new Chart(...)` body is now
`window.renderPriceChart(datasets)`. The function handles canvas lookup, existing-chart
`destroy()`, the "No price data yet" empty path, and all axis/tooltip config. A prior
`no-data-msg` paragraph is removed on re-invocation. `renderPriceChart(window.chartData || [])`
at the bottom preserves current behaviour for the initial load.

## Verification output

```
pytest tests/ -v -k "not slow"

145 passed, 1 deselected

[Same 5 Phase 4 sidebar tests still failing — expected at this stage]
```

Manual smoke: not run at this phase (no browser launch). Phase 4 smoke covers this.

## Commit

`45020dc` — [phase-3.1] extract window.renderPriceChart from charts.js IIFE

## Deviations

None. Palette, axis config, tooltip callbacks all preserved verbatim.

## Confidence

certain
