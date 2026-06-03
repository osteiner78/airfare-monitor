# Plan 014 — Card: Geist fonts, single trend chip, de-duplicated logo

> Tests are orchestrator-owned and written **before** implementation (see "Tests" per phase).

## Context

The dashboard tracker card (`frontend/templates/partials/tracker_card.html`) has accreted into a 3-column grid — `meta | evo-strip | chart panel` — that's too busy for a scan-oriented dashboard. Two changes were decided with the user, plus two cleanups:

1. **Fonts** → switch from Hanken Grotesk + Spline Sans Mono to **Geist + Geist Mono** (sharper, fintech/data feel, first-class tabular figures for price alignment).
2. **Price-change pill** → the `START / 24H / 3H` bordered widget (`.card-evo` / `.evo-strip`) is mostly empty dashes and competes with the chart. Replace it with **one compact trend chip** beside the CURRENT price; the full 3-period breakdown stays on the detail page.
3. **De-dup the airline logo** — it currently renders twice (CURRENT and ALL-TIME, via `best_flight_number` and `historical_best_flight_number`). Keep it only on CURRENT.
4. **Airport codes in mono** (optional, reversible) — render `GVA → BCN` in Geist Mono for a deliberate "departure-board" read.

Outcome: a calmer card whose scan path is route → chart → price, with one momentum signal instead of a sparse table.

Already shipped in prior rounds (do **not** redo): the `one-way` mid-word wrap fix, the `ALL-TIME BEST · NOW` combined-state wording, and the y-rail itself.

## Decisions locked
- Font pairing: **Geist + Geist Mono** (Google Fonts).
- Pill: **single trend chip** near CURRENT; full breakdown remains on detail only.
- Logo: CURRENT only; never on the ALL-TIME stat.
- Chip selection rule (planner): show the **most recent timeframe that actually moved** — priority `3h → 24h → start`; skip `None` and `same` (flat); if nothing moved, render **no chip**. Down = green, up = red, with a small period label (`3h` / `24h` / `start`).

## Out of scope
- No DB/query changes; deltas are already computed in `_enrich_summaries` (`delta_3h`, `delta_24h`, `delta_creation`). The detail page is untouched (keeps its full breakdown).
- No change to the sparkline geometry, the rail positioning, or the at-all-time-low collapse.

---

## Phase 1 — `_primary_delta` selector (pure)

**Intent:** one pure function picks the chip's delta; fully unit-testable, no markup.

**Tasks**
- Add `_primary_delta(summary: dict) -> dict | None` to `backend/pages.py`. Iterate `[("3h", delta_3h), ("24h", delta_24h), ("start", delta_creation)]`; return the first whose delta is non-None and `type in ("up","down")` as `{"period": <label>, "type": <type>, "amount": <amount>}`; else `None`.
- In `_enrich_summaries` (`backend/pages.py`), after the existing `delta_*` assignments, set `s["primary_delta"] = _primary_delta(s)`.

**Files:** `backend/pages.py` only.

**Tests** (`tests/test_pages.py`, written first):
- `test_primary_delta_prefers_3h` — all three moved → `period == "3h"`.
- `test_primary_delta_falls_back_to_24h` — `delta_3h=None`, 24h moved → `"24h"`.
- `test_primary_delta_falls_back_to_start` — 3h & 24h `None` → `"start"` (delta_creation).
- `test_primary_delta_skips_same` — `delta_3h` type `same`, `delta_24h` down → `"24h"`.
- `test_primary_delta_none_when_no_movement` — all `None`/`same` → `None`.
- `test_primary_delta_carries_type_and_amount` — returns the moved delta's `type` and `amount`.

**Verify:** `.venv/bin/python -m pytest tests/test_pages.py -k primary_delta -v` then full suite `-k "not slow"`.

---

## Phase 2 — Card markup + CSS (fonts, chip, logo, 2-col)

**Intent:** collapse the grid back to 2 columns, drop the evo-strip, render the chip, swap fonts, remove the duplicate logo.

**Tasks**
- **Fonts:** in `frontend/templates/base.html` swap the Google-Fonts `<link>` to `family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600`; in `frontend/static/app.css` set `--font-sans: "Geist", ...` and `--font-mono: "Geist Mono", ...` (keep existing system fallbacks). Bump `app.css?v=` in `base.html`.
- **Remove the pill:** delete the `evo_cell` macro and the `.card-evo` / `.evo-strip` block from `tracker_card.html`; return `.card-grid` to 2 columns (meta | panel) in `app.css`; remove the now-orphaned `.card-evo` / `.evo-strip` / `.evo-cell` / `.evo-*` CSS rules.
- **Trend chip:** in `tracker_card.html`, render a `.trend-chip` from `tracker.primary_delta` (arrow + `currency_symbol` + amount + a small `.trend-chip-period`) inside the CURRENT stat — i.e. in `.rail-current`, `.rail-combined`, and the `.panel-fallback` current row — placed just after `.best-price`. Guard with `{% if tracker.primary_delta %}`. Add `.trend-chip` CSS (small inline pill; `.down` green / `.up` red, reusing `--good`/`--bad`).
- **De-dup logo:** remove the `airline_logo(...historical_best_flight_number...)` call from `.rail-alltime` (line ~88) and `.fallback-alltime` (line ~111). Keep CURRENT logos. (`historical_best_flight_number` may become unused in the template — leave the summary field; just stop rendering it.)
- **Codes in mono (optional):** `.route { font-family: var(--font-mono); }` (keep weight/size). Easy to drop if it reads oddly.

**Files:** `frontend/templates/partials/tracker_card.html`, `frontend/static/app.css`, `frontend/templates/base.html`.

**What NOT to touch:** the sparkline SVG / dots, `.rail-*` positioning, status toggle, `last-checked[data-iso]`, and the `best-price` + `filtered-tag` elements (dashboard filter JS depends on them — keep in every branch).

**Tests** (`tests/test_pages.py`, written first; seed via the existing `_seed_history` helper):
- `test_card_has_no_evo_strip` — rendered card does not contain `evo-strip`.
- `test_card_shows_trend_chip_when_moved` — tracker whose current ≠ creation price renders `trend-chip`.
- `test_card_no_trend_chip_when_flat` — tracker with no movement renders no `trend-chip`.
- `test_card_alltime_has_no_logo` — a two-stat (not at-all-time-low) single-airline card renders the airline logo **exactly once** (`text.count("/airline-logo/VY") == 1`). Fail-first: currently 2.
- `test_card_uses_geist_font` — dashboard HTML references `Geist` in the font `<link>`.
- Non-regression: existing dashboard tests stay green (toggle, current-logo present, `€100` currency, weekday + `one-way`, `best-price`/`filtered-tag`, rail/combined/fallback from plan 013).

**Manual smoke** (`.agent/reports/014-phase-2.md`): Geist renders; one trend chip sits by CURRENT (green down / red up, with period); no `START/24H/3H` box; single logo per card; codes-in-mono looks intentional; toggle + delete still work.

**Verify:**
```bash
.venv/bin/python -m pytest tests/test_pages.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
uvicorn backend.main:app --reload   # eyeball the dashboard
```

---

## Proposed CLAUDE.md update (on approval, show diff first)
Update the "Dashboard tracker card" note: fonts are **Geist + Geist Mono**; the card is 2-col (meta | panel); the `START/24H/3H` evo-strip is replaced by a single `.trend-chip` driven by `_primary_delta` (most-recent moved timeframe, `3h→24h→start`, skips flat); the airline logo renders only on the CURRENT stat; the full 3-period breakdown lives on the detail page only.
