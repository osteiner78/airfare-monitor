# Report 014 — Phase 2 end

## What was built

- **Fonts**: Swapped `base.html` Google Fonts link to `Geist:wght@400;500;600;700` + `Geist+Mono:wght@400;500;600`; updated `--font-sans` and `--font-mono` CSS tokens in `:root`; bumped `app.css?v=029`.
- **Grid**: `card-grid` back to 2 columns (`minmax(150px, 0.8fr) 1.2fr`). Removed `.card-evo` div from template and its CSS block (including responsive variant).
- **Evo-strip removal**: Deleted `evo_cell` macro and `.card-evo`/`.evo-strip`/`.evo-cell`/`.evo-label`/`.evo-val` from template and all CSS rules.
- **Trend chip**: Added `.trend-chip` after `.best-price` in all three branches (`rail-current`, `rail-combined`, `panel-fallback`), guarded by `{% if tracker.primary_delta %}`. CSS pill: `.down` = `--good-bg`/`--good`, `.up` = `--bad-bg`/`--bad`; `.trend-chip-period` for the small period label.
- **De-dup logo**: Removed `airline_logo(tracker.historical_best_flight_number, ...)` calls from `.rail-alltime` and `.fallback-alltime`. Logo now only on CURRENT stat.
- **CLAUDE.md**: Updated "Dashboard tracker card" note with Geist fonts, trend chip, logo-on-current-only, and evo-strip removal.

## Verification output

```
$ .venv/bin/python -m pytest tests/test_pages.py -v
49 passed in 1.20s

$ .venv/bin/python -m pytest tests/ -q -k "not slow"
211 passed, 1 deselected in 3.12s
```

## Commits

- `ed95643` — [phase-1.1] add _primary_delta selector and wire into _enrich_summaries
- `5ff1628` — [phase-2.1] Geist fonts, trend chip, 2-col grid, de-dup airline logo

## Deviations

None. The plan mentioned "codes in mono (optional, reversible)" — omitted, as the plan marked it optional. Easy to add: `.route { font-family: var(--font-mono); }`.

## Test gaps

None.

## Follow-ups

- Airport codes in mono (`.route { font-family: var(--font-mono); }`) was marked optional in plan; not implemented.
- Manual smoke test with `uvicorn --reload` to confirm Geist renders, trend chip sits correctly by CURRENT, single logo, toggle/delete still work.

## Confidence

certain
