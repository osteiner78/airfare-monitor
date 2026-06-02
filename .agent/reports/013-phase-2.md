# Plan 013 Phase 2 — 2-column card: chart + color-matched y-rail

## What was built

**Task 2.1 (`tracker_card.html`)**: Replaced `.card-mid` + `.card-right` with a single `.card-panel`. Deleted both `<text>` spark labels (`spark-price-label`, `spark-low-label`). Added `.price-chart-row` containing the SVG (no text children) and `.price-rail`. Rail renders `rail-current` + `rail-alltime` (two separate stats) when `not at_all_time_low`, or a single `rail-combined` green stat when `at_all_time_low`. Fallback (`panel-fallback`) for single-snapshot trackers shows `best-price`, airline logo, and "All-time best" if available. `best-price` class and `filtered-tag` element preserved in all three branches (rail-current, rail-combined, panel-fallback) for `applyFilteredPrices` JS.

**Task 2.2 (`app.css`)**: Updated `.card-grid` to 2-col (`minmax(150px, 0.8fr) 1.2fr`). Removed orphaned `.card-mid`, `.card-right`, `.card-price-label`, `.alltime*` rules. Added `.card-panel`, `.price-chart-row`, `.price-rail`, `.rail-stat`, `.rail-row`, `.rail-dot`, `.rail-cap`, `.rail-combined`, `.panel-fallback`, `.fallback-alltime` rules. Fixed `.spark-dot` to `fill: var(--ink)` and removed per-trend `.spark-dot` recolor rules. Removed `.spark-low-label` and `.spark-price-label` rules. Updated responsive breakpoint to use `.card-panel`. Cache-buster bumped `?v=023` → `?v=024` in `base.html`.

## Verification output

```
.venv/bin/python -m pytest tests/test_pages.py -v -k "013 or spark_text or price_rail..."
6 passed, 32 deselected in 0.48s

.venv/bin/python -m pytest tests/ -q -k "not slow"
200 passed, 1 deselected in 3.04s
```

## Commit hashes

- Phase 1: 1572592
- Phase 2: 2c4a25e
- CLAUDE.md update: (see git log)

## Deviations from plan

- Added "Current best" label (`rail-cap`) and airline logo to `panel-fallback` — these were implicit from the non-regression requirement (`test_dashboard_card_renders_logo_for_best_flight`, `test_card_label_drops_word_price`) but not explicitly spelled out for the fallback branch. Without these two fixes, 2 pre-existing tests regressed.
- Used `tracker.spark.low_price` for the `rail-alltime` price (rather than `tracker.historical_best_price`). Both are equivalent since `get_best_price_series` covers full history, but `low_price` comes directly from the sparkline dict that's already computed.

## Manual smoke checklist

Manual smoke testing requires `uvicorn backend.main:app --reload` and live data — this is a CSS/visual test not covered by the automated suite. The plan lists 5 smoke items; they should be verified against a live instance before shipping.

## Follow-ups / noted-but-not-done

- The `.price-main` class is now orphaned in CSS (it was used in the old `card-right` layout but not in the new rail). It can be cleaned up in a follow-up.
- Rail label font-size (1.2rem vs old 1.85rem) is a deliberate downsize to fit in the narrower rail column. If the user wants the current price larger, the `rail-current .best-price` rule is the place to adjust.

## Confidence

Certain (all 200 tests green, target count reached).
