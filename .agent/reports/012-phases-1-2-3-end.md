# Plan 012 — Phases 1–3 implementation report

## What was built

### Phase 1 — Sparkline correctness (`backend/pages.py`, `tracker_card.html`, `app.css`)
- Rewrote `_sparkline()` with `MIN_SPAN_FRAC=0.06` y-band floor: `span = max(hi-lo, mid*0.06, 1e-9)`, `elo = mid - span/2`. Small price moves now render near-flat; genuine moves use the full height.
- Added `low_x`/`low_y`/`low_price` keys (last occurrence of the series minimum). Removed `first_x`/`first_price`.
- Updated card SVG: replaced start-price text with a green `<circle class="spark-low-dot">` + `<text class="spark-low-label">` at the low point; kept current-point dot and label.
- CSS: `opacity: 0.12 → 0.07` for `.spark-area`; `stroke-width: 1.6 → 1.3` for `.spark-line`; added `.spark-low-dot` and `.spark-low-label` rules.
- Cache-buster: `v=020 → v=021`.

### Phase 2 — Card layout & content polish (`backend/pages.py`, `tracker_card.html`, `app.css`)
- Added `_format_card_date(date_str)` filter → `"Tue 29 Jul"` format (weekday + day + abbreviated month). Registered as `format_card_date`. Malformed input passes through unchanged.
- Card date line now renders `{{ depart_date | format_card_date }} · one-way` (static tag).
- Labels trimmed: `"Current best price"` → `"Current best"`, `"All-time best price"` → `"All-time best"`.
- CSS: `margin-top: auto` removed from `.status-toggle`; `justify-content: center` added to `.card-left` and `.card-mid`; airline logo scoped to `height: 16px` bordered chip inside `.price-main`.
- Cache-buster: `v=021 → v=022`.

### Phase 3 — Currency symbol spacing (`backend/pages.py`)
- `_CURRENCY_SYMBOLS`: `"EUR": "€ "` → `"€"`, same for USD/GBP. CHF keeps `"CHF "`. Fallback lambda unchanged.
- No template changes needed (filter output flows through automatically).

## Verification output

```
$ .venv/bin/python -m pytest tests/ -q -k "not slow"
182 passed, 1 deselected in 3.16s
```

Sparkline-only run:
```
$ .venv/bin/python -m pytest tests/test_sparkline.py -v
16 passed in 0.30s
```

## Commit hashes

- `78d9944` — `[phase-1.1]` sparkline implementation
- `dc3d07d` — `[phase-2+3]` card polish + currency fix

## Deviations from plan

- None. All tasks implemented exactly as specified.

## Test gaps flagged / new tests added

- None. All orchestrator tests pass. No discovery gaps encountered.

## Follow-ups (noted, not done)

- Phase 4 (page-chrome polish: Monitor link, CTA palette, native date input) is optional and was not implemented in this session.
- City-name expansion of airport codes: deferred per plan.

## Confidence rating

**certain** — all 182 tests green, implementation matches plan spec exactly.
