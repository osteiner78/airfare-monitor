# 004 — Start Report

## Scope

Six phases: delete dead `detail_content.html` partial, fix chart rendering (instance cleanup, empty state, date fallback), restructure tracker card to fix pause-navigation conflict, add best/historical price to detail header, improve booking links and date formatting, final polish.

## Tests to turn green

- **Phase 4**: 3 new tests in `tests/test_best_price.py` — all currently fail with ImportError (function not yet implemented)

## Pre-work observations

- Baseline: 87 passed, 3 fail (test_best_price.py ImportError) — all fail for the right reason.
- `detail_content.html` is dead code (superseded by `detail_page.html` in plan 003).
- Search-now route returns `detail_content.html` (no header) → should return `detail_page.html` instead.
- Card `hx-get` on outer div + child `hx-patch` button causes pause click to also trigger navigation.
