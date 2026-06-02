# Plan 013 — Tracker card: 2-column price panel with a color-matched y-rail

## Context

Plan 012 fixed the sparkline's scale and added two dots (green = all-time low, trend-colored = current) plus two `<text>` price labels on the chart. Those labels are **redundant** (they repeat the ALL-TIME BEST and CURRENT BEST numbers shown elsewhere on the card) and they **overprint** whenever the price is at its all-time low right now — i.e. `€29€29`, `€568€868` on exactly the "great deal" cards. See the review screenshot.

The decided fix (with the user): **remove the chart text labels** and bind each dot to its number by (a) **color** and (b) **co-location** — collapsing the card from 3 columns to 2, and floating the CURRENT and ALL-TIME numbers in a **y-rail** beside the chart, each at the height of its dot, like a price axis.

Current implementation to modify:
- `backend/pages.py::_sparkline` (pure; ~168-208) — returns `points/area/low_*/last_*/label_y/trend/w/h`; `h` includes an 11px label band; the current dot follows the **trend** color via CSS.
- `frontend/templates/partials/tracker_card.html` — 3-col grid (`.card-left` meta | `.card-mid` chart+all-time | `.card-right` current+evo+fetch), with two `<text>` spark labels (lines 57-58).
- `frontend/static/app.css` — `.card-grid { grid-template-columns: 33% 1fr 1fr; }`, `.card-mid`, `.card-right`, `.spark*` (note `.spark-down/.spark-up/.spark-flat .spark-dot` recolor the current dot by trend; `.spark-low-dot` is green).

### Decisions locked with the user
- **Layout:** 2 columns — `meta` (left, unchanged) | `price panel` (right, merges old middle+right). The middle divider goes away.
- **Y-rail:** the CURRENT and ALL-TIME numbers float to the right of the chart, vertically aligned to their dots (current higher, all-time lower — current price is always ≥ all-time low, so this order never inverts).
- **Color mapping:** chart **line/area = net trend** (red up / green down, unchanged); **all-time-low dot + ALL-TIME number = green** (`--good`); **current dot + CURRENT number = ink** (`--ink`) — this means the current dot **stops following the trend color**.
- **Hierarchy preserved:** the rail's CURRENT number stays prominent (larger, ink, bold); ALL-TIME is smaller and green. CURRENT is still the headline, just relocated to its dot height.
- **Collision handling:** (1) `at_all_time_low` (current == all-time min) → render a **single** combined green stat ("all-time low, now"), since the dots coincide; (2) otherwise a server-computed **minimum-gap** separates the two rail labels so they never overlap.
- **No chart text labels** — they are deleted (this is the headline fix).

### Decisions made by the planner
- The de-collision math is a small **pure helper** `_rail_positions(current_frac, low_frac)` returning two clamped fractions ≥ `_MIN_GAP_FRAC` apart, both within `[_RAIL_MARGIN, 1-_RAIL_MARGIN]`. Lives in `pages.py`, unit-tested in isolation.
- `_sparkline` returns vertical **fractions** (`last_y_frac`, `low_y_frac` in 0..1) plus the de-collided `current_rail` / `alltime_rail` fractions and the `at_all_time_low` flag, so the template positions rail labels with `top: <frac*100>%` and needs no pixel math.
- `at_all_time_low := last_price == low_price` (equivalently `best_price == historical_best_price`, since the series is full history — see plan 012).

### Out of scope 
- No DB/query changes; `get_best_price_series` and the summaries query are untouched.
- No JS (positioning is pure CSS `top: %` + server-computed fractions).
- Detail page, evo-strip semantics, currency filter — unchanged.
- Phase-4 chrome polish from plan 012 (Add Route button color, native date input) is still deferred.

### Tests are pre-written by the orchestrator — do not re-author or weaken
All fail-first tests already exist and currently **fail on purpose**; implement until green.
- **Phase 1:** 12 tests appended to `tests/test_sparkline.py` (rail fractions, `at_all_time_low`, `_rail_positions` de-collision).
- **Phase 2:** 6 tests in the `=== Plan 013 ===` block of `tests/test_pages.py` (labels removed, rail present, combined state, two-stat state, fallback, `best-price`/`filtered-tag` non-regression).
- Per `CLAUDE.md` test ownership the executor implements until green and must not modify these. No existing plan-012 test needs changing (none assert `label_y`; `test_step_series_coords_within_bounds` uses `s["h"]`, still valid when `h` drops to 34).
- **State now:** `17 failed, 183 passed, 1 deselected`. **Target after both phases:** those 17 green → **200 passed, 1 deselected**, zero regressions.

---

## Phase 1 — `_sparkline` rail geometry + de-collision (pure)

### Intent
Give the template everything it needs to place the two rail labels at dot height, never overlapping, and to know when to switch to the combined "at all-time low" state. Pure functions only — fully fail-first unit-tested. No markup yet.

### `_sparkline` contract changes
Remove:
- `label_y` (no chart text anymore).
- the label band: return `"h": h` (the passed height, default 34), **not** `h + label_h`. Drop `label_h`.

Add:
- `last_y_frac = round(last_y / h, 4)` and `low_y_frac = round(low_y / h, 4)` — 0 = top (priciest), 1 = bottom (cheapest).
- `at_all_time_low: bool = (last_price == low_price)`.
- `current_rail, alltime_rail = _rail_positions(last_y_frac, low_y_frac)` — de-collided fractions for label `top`.

Keep `points`, `area`, `low_x/low_y/low_price`, `last_x/last_y/last_price`, `trend`, `w`, `h`.

### `_rail_positions(current_frac, low_frac)` (new pure helper)
Module constants: `_MIN_GAP_FRAC = 0.40`, `_RAIL_MARGIN = 0.14`. Precondition `current_frac <= low_frac` (current price ≥ all-time low ⇒ current sits higher ⇒ smaller frac). Algorithm:
```
c, a = current_frac, low_frac
if a - c < _MIN_GAP_FRAC:
    m = (c + a) / 2
    c, a = m - _MIN_GAP_FRAC / 2, m + _MIN_GAP_FRAC / 2
# clamp into [_RAIL_MARGIN, 1 - _RAIL_MARGIN], preserving the gap
if c < _RAIL_MARGIN:
    c, a = _RAIL_MARGIN, max(a, _RAIL_MARGIN + _MIN_GAP_FRAC)
if a > 1 - _RAIL_MARGIN:
    a, c = 1 - _RAIL_MARGIN, min(c, 1 - _RAIL_MARGIN - _MIN_GAP_FRAC)
return round(c, 4), round(a, 4)
```
(With `_MIN_GAP_FRAC + 2*_RAIL_MARGIN = 0.68 ≤ 1`, both clamps are always satisfiable.)

### Tasks
1.1 Add `_rail_positions` + the two constants to `backend/pages.py`.
1.2 Rewrite `_sparkline`'s return per the contract above (drop `label_y`/label band; add `last_y_frac`, `low_y_frac`, `at_all_time_low`, `current_rail`, `alltime_rail`).

### Files
- Modify: `backend/pages.py` (`_sparkline` + new helper/constants only)

### What NOT to touch
- `_enrich_summaries`, `get_best_price_series`, the summaries query, `_compute_delta`.
- Any template/CSS (Phase 2).

### Tests — append to `tests/test_sparkline.py`
NEW-BEHAVIOR (fail now, pass after):
- `test_returns_rail_fractions` — result has `last_y_frac`, `low_y_frac`, `current_rail`, `alltime_rail`, all in `[0, 1]`.
- `test_label_band_removed` — `"label_y" not in s`; `_spark([300, 600])["h"] == 34`.
- `test_current_rail_above_alltime` — for any series, `current_rail <= alltime_rail` (current never below all-time in the rail).
- `test_rail_gap_enforced_when_dots_close` — `_spark([450, 451])`: `alltime_rail - current_rail >= 0.40 - 1e-6` (pushed apart).
- `test_rail_unchanged_when_dots_far` — `_spark([300, 600])`: `current_rail` ≈ `last_y_frac` and `alltime_rail` ≈ `low_y_frac` (no push; tolerance 1e-6).
- `test_at_all_time_low_true_when_current_is_min` — `_spark([100, 80])["at_all_time_low"] is True`.
- `test_at_all_time_low_false_when_current_above_min` — `_spark([80, 100])["at_all_time_low"] is False`.
- `test_at_all_time_low_true_when_min_repeats_at_end` — `_spark([90, 80, 80])["at_all_time_low"] is True`.

`_rail_positions` unit tests:
- `test_rail_positions_far_apart_unchanged` — `_rail_positions(0.1, 0.9) == (0.1, 0.9)`.
- `test_rail_positions_close_pushed_symmetric` — `_rail_positions(0.50, 0.52)` → gap ≥ 0.40, centered near 0.51.
- `test_rail_positions_clamped_at_top` — `_rail_positions(0.02, 0.05)`: `c == _RAIL_MARGIN` and `a - c >= _MIN_GAP_FRAC`.
- `test_rail_positions_clamped_at_bottom` — `_rail_positions(0.95, 0.99)`: `a == 1 - _RAIL_MARGIN` and `a - c >= _MIN_GAP_FRAC`.
- `test_rail_positions_within_margins` — for several inputs, both outputs in `[_RAIL_MARGIN, 1 - _RAIL_MARGIN]`.

NON-REGRESSION:
- All existing `tests/test_sparkline.py` cases still pass (scaling floor, low marker, trend, edges).

### Verification
```bash
.venv/bin/python -m pytest tests/test_sparkline.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
```
Paste into `.agent/reports/013-phase-1.md`.

---

## Phase 2 — 2-column card: chart + color-matched y-rail (markup + CSS)

### Intent
Render the new panel: meta on the left; on the right a chart row (sparkline + rail), then the evo-strip, then last-fetch. Delete the chart text labels. Bind dots to numbers by color and height. Handle the `at_all_time_low` combined state and the no-spark fallback.

### Tasks
2.1 `tracker_card.html` — restructure the right side:
   - Replace `.card-mid` + `.card-right` with a single `.card-panel`.
   - **Delete** the two `<text class="spark-low-label">` / `<text class="spark-price-label">` elements.
   - `.price-chart-row` (position: relative): the `.spark` svg (`viewBox="0 0 {{w}} {{h}}"`, h now 34) on the left with `.spark-area`, `.spark-line`, `.spark-low-dot` (green), `.spark-dot` (ink); and a `.price-rail` on the right.
   - In `.price-rail`, when **not** `spark.at_all_time_low`, two absolutely-positioned blocks:
     - `.rail-stat.rail-current` at `style="top:{{ (spark.current_rail*100)|round(2) }}%"` — a green/ink dot swatch + `<span class="best-price">{{ currency_symbol }}{{ best_price }}</span>` + airline logo + a `.rail-cap` "Current best". **Keep the `best-price` class and a hidden `.filtered-tag`** (dashboard JS depends on them).
     - `.rail-stat.rail-alltime` at `top:{{ spark.alltime_rail*100 }}%` — green dot + smaller green `{{ historical_best_price }}` + `.rail-cap` "All-time best".
   - When `spark.at_all_time_low`, render a single centered `.rail-stat.rail-combined` (green): the price (keep `best-price` class + `.filtered-tag`) + a small "All-time low - now" caption. Do not also render the two separate stats.
   - **No-spark fallback** (`spark` is falsy, e.g. <2 snapshots): render a simple stacked `.panel-fallback` with Current best (big, `best-price` + `.filtered-tag`) and, if `historical_best_price`, All-time best — no chart, no rail.
   - Keep the evo-strip and the `.meta-fetch`/`.last-checked[data-iso]` block below the chart row (unchanged).
2.2 `app.css`:
   - `.card-grid { grid-template-columns: minmax(150px, 0.8fr) 1.2fr; }` (2-col).
   - Add `.card-panel` (flex column, padding, `border-left: 1px solid var(--line-soft)`), `.price-chart-row` (display:flex; position:relative; height ~76px; gap), `.price-chart-row .spark { flex:1; height:100%; aspect-ratio:auto; }`, `.price-rail { position:relative; width: 104px; flex-shrink:0; }`.
   - `.rail-stat { position:absolute; right:0; transform: translateY(-50%); display:flex; flex-direction:column; ... }`; `.rail-current .best-price` larger/ink/bold; `.rail-alltime` smaller; `.rail-dot` swatch (8px circle) with `.rail-dot.current{background:var(--ink)}` / `.rail-dot.alltime{background:var(--good)}`; `.rail-cap` faint uppercase micro-label.
   - `.rail-combined` centered (`top:50%`), green emphasis.
   - **Recolor the current dot to ink:** `.spark-dot { fill: var(--ink); }` and **remove** the `.spark-down/.spark-up/.spark-flat .spark-dot { stroke: ... }` recolor rules (the line/area keep trend color; the dot does not). Keep `.spark-low-dot` green.
   - Delete `.spark-low-label` / `.spark-price-label` rules; update `.spark` `aspect-ratio` (now driven by `.price-chart-row` height, so it can be removed from `.spark`).
   - Remove the now-unused `.card-mid` / `.card-right` / `.alltime*` rules (orphaned by 2.1) — mention any that are shared before deleting.
   - Bump `app.css?v=023` → `?v=024` in `base.html`.

### Files
- Modify: `frontend/templates/partials/tracker_card.html`, `frontend/static/app.css`, `frontend/templates/base.html`

### What NOT to touch
- `.card-left` meta column and its hover/HTMX behavior.
- The evo-strip macro/markup and `.last-checked[data-iso]` (relative-time JS).
- `_sparkline` (finalized in Phase 1).

### Tests — `=== Plan 013 ===` block in `tests/test_pages.py`
NEW-BEHAVIOR (need ≥2 snapshots so `spark` renders):
- `test_card_has_no_spark_text_labels` — rendered card contains neither `spark-price-label` nor `spark-low-label` (the overlap fix).
- `test_card_renders_price_rail` — card contains `price-rail` and `rail-current` (and `rail-alltime` when not at all-time low).
- `test_card_keeps_best_price_class_for_filter_js` — `best-price` class and a `filtered-tag` element still present (dashboard `applyFilteredPrices` depends on them).
- `test_card_at_all_time_low_shows_combined_stat` — tracker whose latest snapshot is the cheapest ever (e.g. snaps 100 → 80) renders `rail-combined` and an "all-time low" caption, and does **not** render two separate rail numbers for the same value.
- `test_card_not_at_all_time_low_shows_two_rail_stats` — tracker priced above its historical low (e.g. snaps 80 → 100) renders both `rail-current` and `rail-alltime`.
- `test_card_without_history_uses_fallback` — single-snapshot tracker (no spark) still shows the current best price (and `best-price` class) via `panel-fallback`, no `price-rail`.

NON-REGRESSION:
- Existing dashboard tests stay green (toggle, logo, currency `€100`, weekday, one-way, labels).
- Full suite green.

Color/positioning (CSS) — **no automated coverage**; manual smoke below.

### Manual smoke (record in `.agent/reports/013-phase-2.md`)
1. A normal mover (e.g. GVA→BCN €47): ink current dot + ink CURRENT number aligned to the right-end dot; green low dot + green ALL-TIME number aligned to the low dot; no overlap, no chart text. ✓
2. A "great deal" card (current == all-time low, e.g. €29): single green "all-time low - now" stat; dots coincide; no `€29€29` overprint. ✓
3. Dots' colors visibly match their numbers; line/area still red-up / green-down. ✓
4. Single-snapshot tracker: fallback shows current best, no broken chart. ✓
5. Status toggle + delete still work (HTMX). Filtered-price JS still overwrites the current number. ✓

### Verification
```bash
.venv/bin/python -m pytest tests/test_pages.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
uvicorn backend.main:app --reload   # eyeball the dashboard
```
Paste pytest output + smoke results into `.agent/reports/013-phase-2.md`.

---

## Handoff notes
- Do Phase 1 (pure, fast, fully tested) and get it green before touching markup.
- The current dot color changes from **trend** to **ink** — remember to delete the `.spark-*  .spark-dot` trend rules, or the dot will fight the new scheme.
- **`best-price` + `filtered-tag` must survive** in every branch (rail-current, rail-combined, fallback) — `frontend/static/filters.js` / dashboard `applyFilteredPrices` overwrite `.best-price.textContent` and toggle `.filtered-tag`. This coupling already bit us once.
- Run tests with `.venv/bin/python -m pytest`.
- Cache-buster: bump `base.html` `app.css?v=` once in Phase 2.

## Proposed CLAUDE.md addition (apply on approval — show diff first)
Append to "Future me notes": *"Card price rail (plan 013): the dashboard card is 2-col (meta | price panel). The sparkline has no text labels; two dots (ink = current, green = all-time low) are bound to numbers floated in a y-rail beside the chart at the dots' heights. `_sparkline` returns `last_y_frac`/`low_y_frac`, de-collided `current_rail`/`alltime_rail` (via `_rail_positions`, min gap `_MIN_GAP_FRAC=0.40`, margin `_RAIL_MARGIN=0.14`), and `at_all_time_low` (current==historical min) which collapses the rail into one green 'all-time low' stat. The current dot is ink (no longer trend-colored); line/area keep trend color. `best-price`+`filtered-tag` are preserved in all branches for the dashboard filter JS."* Update the test-count line after the new tests land.
