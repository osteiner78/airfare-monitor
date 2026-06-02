# Plan 012 — Tracker card: sparkline correctness + layout/content polish

## Context

The dashboard tracker card was redesigned into a 3-column grid (`frontend/templates/partials/tracker_card.html`):
- **Left** — route (`GVA → BCN`), depart date, ACTIVE/PAUSED pill.
- **Middle** — full-history sparkline (`backend/pages.py::_sparkline`) + "ALL-TIME BEST PRICE".
- **Right** — "CURRENT BEST PRICE" (big mono number + airline logo), the START/24H/3H evolution strip, and "Last price fetch".

A design review flagged real problems. This plan fixes them. The biggest is **the sparkline misrepresents the data**: it auto-scales y to the visible min/max, so a €1 wiggle on a €450 fare renders as a dramatic comb that looks broken; the heavy red area-fill amplifies the alarm; and the endpoint price labels (`first`/`last`) don't mark the visible low, so the curve appears to contradict the "all-time best" number sitting right beside it.

Data facts confirmed (do not re-litigate):
- `backend/db.py::get_best_price_series()` returns `dict[tracker_id -> list[float]]`, **one best-price per snapshot, full history, ordered by time** (no window). So `min(series[id]) == historical_best_price` for that tracker — the all-time low *is* on the curve; it just isn't marked.
- `_sparkline(prices, w=132, h=34, pad=4)` is a **pure function** → fully unit-testable, fail-first.
- `get_tracker_summaries()` does `SELECT t.*`, so each summary already carries `return_date`, `currency`, etc. No DB/query changes anywhere in this plan.
- The `currency_symbol` filter (`backend/pages.py:114-115`) returns `"€ "` (trailing space). It is consumed by: the card, the detail page (`window.chartCurrency`), `frontend/static/filters.js` ("Best now: " + currency + price) and the dashboard `filteredBest` localStorage path. **`tests/test_filters.py:407` pins `"€ 90"`.**

### Decisions locked (planner)
- **Sparkline y-scaling:** floor the visual band to a fraction of the price level so trivial moves look trivial. `MIN_SPAN_FRAC = 0.06` (band is at least ±3% of the mean). When the real range is smaller than the floor, **center** the data in the band; when larger, use the real range (no inflation). This is the core fix.
- **Mark the all-time low**, not the series start. Drop the start-price label (it duplicates the evo-strip "Start"). The low marker is always drawn in `--good` (green) regardless of trend — the lowest price is, by definition, the best. Keep the current (last) point dot in the trend color.
- **Lighter chart ink:** area-fill opacity `0.12 → 0.07`, line `1.6 → 1.3`. Color should not blanket the card.
- **Label wording:** drop the redundant "PRICE" → **"Current best"** and **"All-time best"**.
- **Currency spacing:** trim EUR/USD/GBP to no trailing space (`"€"`, `"$"`, `"£"`); keep CHF as `"CHF "` (3-letter code needs separation). This is **global** for consistency; the one pinned test is updated by the orchestrator (see Phase 3).
- **Date:** card depart date gains a weekday and a static `· one-way` tag → `Tue 29 Jul · one-way`. Implemented as a **new** card-only filter; `_format_date` stays untouched (it is reused by flight times in the results table). All trips are one-way today; **round-trip is a future feature** — the tag is hard-coded "one-way" now (no `return_date` branching) purely to set the expectation for users.
- **Logo:** keep the `airline_logo` macro as-is; tame it with CSS only (smaller, rounded chip, hairline border — **no desaturation**, that looks off-brand).
- **Layout void:** vertically **center** the left and middle columns against the taller right column, and move the status pill up under the route (drop `margin-top:auto`). This removes the top-heavy dead space without forcing a fixed card height.

### Tests are already written (orchestrator) — DO NOT re-author or weaken them
All fail-first tests for this plan exist and currently **fail on purpose**. The executor implements until they pass; per `CLAUDE.md` test ownership, do not modify them (the single exception — `tests/test_filters.py:407` — was already applied by the orchestrator).
- **Phase 1:** `tests/test_sparkline.py` (16 tests; 10 fail / 6 pass today — the 6 are preserved behavior).
- **Phases 2–3:** the `=== Plan 012 ===` block at the end of `tests/test_pages.py` (8 tests).
- **Sanctioned edit:** `tests/test_filters.py:407` already changed `"€ 90"` → `"€90"` (fails until Phase 3).
Baseline before this plan: **158 passed, 1 deselected**. Target after all phases: those 158 still green **plus** the 24 new tests, with the sanctioned filter test green again.

### Out of scope (state explicitly, do not build)
- No DB schema/query changes; no new endpoints.
- No sorting/grouping/filtering of the dashboard list.
- No changes to the tracker **detail** page chart (`charts.js`) or its filter sidebar.
- City-name expansion of airport codes (deferred).
- **Round-trip / return flights** are a future feature — this plan only adds a static "one-way" label, no return logic.
- Phase 4 page-chrome polish is **optional** and must not block Phases 1–3.

---

## Phase 1 — Sparkline correctness (scaling floor, low marker, lighter ink)

### Intent
Make the sparkline tell the truth: small price moves look small, large moves use the height, and the visible low is marked so it agrees with the "all-time best" number beside it. All logic lives in the **pure** `_sparkline()` function plus the card template's SVG and CSS — no data layer, no other pages. After this phase a €1 oscillation on a €450 fare reads as a near-flat line with a small green low-marker, not a heartbeat.

### New `_sparkline()` return contract
Replace the current return dict. Keys the template/tests rely on:
- `points` — polyline points string (unchanged format).
- `area` — polygon points string for the fill (unchanged format).
- `last_x`, `last_y`, `last_price` — current point (dot + optional label), trend-colored.
- `low_x`, `low_y`, `low_price` — **NEW**: the all-time-low point (green marker + label). Pick the **last** index where `price == lo` (most recent time the low was seen).
- `label_y` — text baseline (as today).
- `trend` — `"down" | "up" | "flat"` (first-vs-last, unchanged semantics).
- `w`, `h` — viewBox dims (note `h` already includes the label band).
- **Remove** `first_x`, `first_price` (start label retired).

### Scaling math (implement exactly)
```
MIN_SPAN_FRAC = 0.06
pts = [p for p in prices if p is not None]
if len(pts) < 2: return None
lo, hi = min(pts), max(pts)
mid  = (lo + hi) / 2
floor = mid * MIN_SPAN_FRAC
span = max(hi - lo, floor, 1e-9)
elo  = mid - span / 2          # effective bottom-of-band value
# y(p) = pad + (h - 2*pad) * (1 - (p - elo) / span)
```
Coordinate space (unchanged from today, stated explicitly so tests pin it): the **plot band is `[pad, h - pad]` using the passed `h`** (default 34, so `[4, 30]`, vertical center `17`). The returned `h` is `passed_h + label_band` (the price `<text>` sits below the plot at `label_y`). So a flat/near-flat line sits at y≈17; the cheapest price maps toward y≈`h-pad` (bottom), the priciest toward y≈`pad` (top).
- Flat series (`hi == lo`): `span == floor`, every point maps to the vertical center → flat midline (no div-by-zero; preserve the existing `span == 0` guard as a fast path returning mid).
- `x(i)` mapping is unchanged.
- `low_*` / `last_*` use the same `x`/`y`.

### Tasks
1.1 `backend/pages.py::_sparkline` — implement the scaling math + new contract above. Keep signature `(prices, w=132, h=34, pad=4)`.
1.2 `frontend/templates/partials/tracker_card.html` (middle column SVG, ~lines 50-58):
   - Remove the **start** `<text>` label (the one at `first_x`).
   - Keep the current-point `<circle class="spark-dot">` at `last_x,last_y`.
   - Add a **low** marker `<circle class="spark-low-dot" cx="{{ spark.low_x }}" cy="{{ spark.low_y }}" r="2.2"/>` and a low `<text class="spark-low-label" x=... y="{{ spark.label_y }}">{{ currency_symbol }}{{ low_price }}</text>`.
   - Keep the current-price `<text>` label at `last_x` (right-anchored) — this is the "now" endpoint.
1.3 `frontend/static/app.css`:
   - `.spark-area { opacity: 0.07; }` (from 0.12).
   - `.spark-line { stroke-width: 1.3; }` (from 1.6).
   - Add `.spark-low-dot { fill: var(--good); stroke: #fff; stroke-width: 1.2; }` and `.spark-low-label { fill: var(--good); }` (reuse `.spark-price-label` sizing).
   - Bump `app.css?v=020` → `?v=021` in `base.html`.

### Files
- Modify: `backend/pages.py` (`_sparkline` only)
- Modify: `frontend/templates/partials/tracker_card.html` (SVG markup only)
- Modify: `frontend/static/app.css` (spark rules)
- Modify: `frontend/templates/base.html` (cache-buster bump)

### What NOT to touch
- `backend/db.py::get_best_price_series` / any query.
- `_enrich_summaries`, `_compute_delta`, the evo-strip, the delta fields.
- `frontend/static/charts.js`, `filters.js` (detail-page chart is unrelated).
- The left/right columns of the card (Phase 2).

### Tests — new file `tests/test_sparkline.py`
NEW-BEHAVIOR (fail now, pass after):
- `test_returns_none_for_fewer_than_two_points` — `_sparkline([]) is None`, `_sparkline([100]) is None`.
- `test_small_relative_change_stays_near_flat` — `_sparkline([450, 451])`: `abs(low_y - last_y)` is a **small** fraction of plotting height (assert `< 0.15 * chart_h`), i.e. the €1 move does not span the chart. Both y within the central third.
- `test_large_relative_change_uses_full_height` — `_sparkline([300, 600])`: min point near bottom (`y ≈ chart_h - pad`, within tolerance), max near top (`y ≈ pad`). Confirms no over-inflation when the real range exceeds the floor.
- `test_flat_series_is_midline` — `_sparkline([400, 400, 400])`: all y equal to the vertical center; `trend == "flat"`.
- `test_low_marker_is_series_min` — `_sparkline([500, 480, 495])`: `low_price == 480`.
- `test_low_marker_picks_most_recent_min` — `_sparkline([480, 500, 480])`: `low_x` corresponds to the **last** index (2), not the first.
- `test_trend_down_up_flat` — `[100,90] → "down"`, `[90,100] → "up"`, `[100,100] → "flat"`.
- `test_start_label_keys_removed` — returned dict has no `first_x`/`first_price` keys; has `low_x`/`low_y`/`low_price`.

FAILURE-MODE / EDGE:
- `test_filters_none_values` — `_sparkline([100, None, 120])` ignores `None`, treats as 2 points, no crash.
- `test_two_identical_prices_no_div_by_zero` — `_sparkline([200, 200])` returns midline, no exception.
- `test_step_series_does_not_crash` — `_sparkline([450,450,451,450,451,451])` returns valid coords within `[0, w] × [0, h]`.
- `test_near_zero_prices` — `_sparkline([1, 2])` does not divide by zero and returns finite coords.

NON-REGRESSION:
- Full suite must stay green (currently **158 passed, 1 deselected**).

### Verification
```bash
cd /Users/oliversteiner/Documents/code/airfare-monitor
.venv/bin/python -m pytest tests/test_sparkline.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
```
Manual: `uvicorn backend.main:app --reload`, open `/`, confirm a €1-oscillation tracker (e.g. GRU→CDG) now reads near-flat with a green low marker, and a real mover (Vueling, ↓€8) still shows a clear slope. Paste pytest output + a one-line visual confirmation into `.agent/reports/012-phase-1.md`.

---

## Phase 2 — Card layout & content polish (alignment, labels, date, logo)

### Intent
Remove the dead vertical space, cut label noise, make the date useful, and stop the airline logo from out-shouting the price. Template + CSS only; no behavior or data change. The card should read like a calm finance row, columns visually balanced.

### Tasks
2.1 **Labels** (`tracker_card.html`): `Current best price` → `Current best`; `All-time best price` → `All-time best`.
2.2 **Date + one-way tag**: add a card-only Jinja filter in `backend/pages.py`, e.g. `_format_card_date(date_str) -> "%a %-d %b"` (`Tue 29 Jul`); register as `format_card_date`. In the card, render `{{ tracker.depart_date | format_card_date }}` followed by a **static** `· one-way` tag (all flights are one-way today; round-trip is a future feature — do **not** branch on `return_date`). **Do not** modify `_format_date`.
2.3 **Logo taming** (`app.css`, scoped to `.price-main`): constrain `.price-main .airline-logo { height: 16px; width: auto; border-radius: 3px; }`, wrap container `.price-main .airline-logo-wrap { border: 1px solid var(--line); border-radius: 4px; padding: 1px; line-height: 0; }`. No `filter`/desaturate. Keep the `airline_logo` macro untouched.
2.4 **Layout balance** (`app.css`):
   - `.status-toggle { /* remove */ margin-top: auto; }` → drop it; add small `gap` so the pill sits under the date.
   - `.card-left { justify-content: center; }` and `.card-mid { justify-content: center; }` so the lighter columns center against the taller right column.
   - Verify the column rule `.card-grid { grid-template-columns: 33% 1fr 1fr; }` still reads well; if the middle feels cramped, widen route column slightly (e.g. `minmax(150px, 0.9fr) 1.1fr 1.1fr`) — planner's discretion, keep it minimal.
2.5 Bump `app.css?v=021` → `?v=022` in `base.html`.

### Files
- Modify: `backend/pages.py` (new `_format_card_date` filter only)
- Modify: `frontend/templates/partials/tracker_card.html`
- Modify: `frontend/static/app.css`
- Modify: `frontend/templates/base.html` (cache-buster)

### What NOT to touch
- `_format_date` (reused by `_split_timestamps` / results table).
- The sparkline (Phase 1) and the evo-strip / delta logic.
- The `airline_logo` macro and `_airline_code` filter.
- `get_tracker_summaries` / any query.

### Tests — add to `tests/test_pages.py`
NEW-BEHAVIOR:
- `test_card_label_drops_word_price` — rendered dashboard contains `Current best` and `All-time best`, and does **not** contain `CURRENT BEST PRICE`.
- `test_card_date_includes_weekday` — the card's depart-date text matches `^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b` (render a tracker with a known `depart_date`, assert the weekday is correct for that date).
- `test_card_shows_one_way_tag` — every rendered card contains `one-way` (static tag, no `return_date` branching).
- `test_format_card_date_filter_unit` — `_format_card_date("2026-07-29") == "Tue 29 Jul"` (or the platform's `%a %-d %b`); and malformed input returns the input unchanged (mirror `_format_date`'s `except` behavior).

NON-REGRESSION:
- Existing `test_pages.py` dashboard render tests stay green (status 200, prices present, toggle present).
- Full suite green.

Client-side visual (centering, logo chip): **no automated coverage** (pytest-only repo) — verify in the manual smoke below.

### Manual smoke (record in `.agent/reports/012-phase-2.md`)
1. Cards no longer show a large empty gap in the left/middle columns; route/date/status read as a centered group. ✓
2. Date shows weekday + `one-way`/`round trip`. ✓
3. Airline logo is a small bordered chip; the price is the brightest element. ✓
4. ACTIVE/PAUSED toggle still flips on click (HTMX swap intact). ✓

### Verification
```bash
.venv/bin/python -m pytest tests/test_pages.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
uvicorn backend.main:app --reload   # eyeball the dashboard
```
Paste pytest output + smoke results into `.agent/reports/012-phase-2.md`.

---

## Phase 3 — Currency symbol spacing (global, with sanctioned test update)

### Intent
Render `€47` not `€ 47` everywhere, consistently. Small change, but it touches a globally-shared filter consumed by the card, the detail page (`window.chartCurrency`), `filters.js`, and the dashboard `filteredBest` path — and **one existing test pins the old value**. Isolated as its own phase so the regression surface is explicit.

### Tasks
3.1 `backend/pages.py:114` — change `_CURRENCY_SYMBOLS` to `{"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}` (CHF keeps its space). Leave the fallback lambda behavior (`(c or "") + " "`) **as-is** so unknown codes still get a separator.
3.2 **Sanctioned test update** (explicitly approved by the user; included here so it is NOT a silent weakening by the executor): in `tests/test_filters.py:407`, change the assertion `"€ 90"` → `"€90"`. The executor applies exactly this one-token change and nothing else in that file.
3.3 Bump `app.css?v=022` → `?v=023` in `base.html` (no CSS change strictly needed, but keeps the version monotonic if Phase 2 already bumped; skip if untouched).

### Files
- Modify: `backend/pages.py` (`_CURRENCY_SYMBOLS` dict)
- Modify: `tests/test_filters.py` (line 407 only — sanctioned above)

### What NOT to touch
- The fallback lambda; CHF spacing.
- Any template (the filter output flows through automatically).
- `filters.js` / `charts.js` — they concatenate the symbol; `"€" + 90` → `"€90"` is the intended result.

### Tests
NEW-BEHAVIOR (add to `tests/test_pages.py` or `tests/test_filters.py`):
- `test_currency_symbol_eur_has_no_trailing_space` — the `currency_symbol` filter / `_CURRENCY_SYMBOLS["EUR"]` equals `"€"`.
- `test_currency_symbol_chf_keeps_space` — CHF still renders `"CHF "` (so `CHF 120`, not `CHF120`).
- `test_unknown_currency_still_separated` — `currency_symbol("XYZ")` ends with a space (fallback unchanged).

NON-REGRESSION:
- `tests/test_filters.py` passes **with** the sanctioned line-407 edit.
- Full suite green. Grep the rendered detail page once to confirm `window.chartCurrency = "€"` (no stray space): `curl -s localhost:8000/trackers/1 | grep chartCurrency`.

### Verification
```bash
.venv/bin/python -m pytest tests/test_filters.py tests/test_pages.py -v
.venv/bin/python -m pytest tests/ -q -k "not slow"
```
Paste output into `.agent/reports/012-phase-3.md`. Phase 3 is complete when the suite is green (count rises by the 3 new tests; the line-407 test still passes against `"€90"`).

---

## Phase 4 — Page-chrome polish (OPTIONAL, non-blocking)

### Intent
Minor consistency fixes from the review. Do **not** let this block 1–3; ship it only if 1–3 are green. CSS/markup only.

### Tasks (each independent — partial is fine)
4.1 **Monitor link affordance** (`dashboard.html` / `app.css`): give the "Monitor" link the same button shape as "Refresh All" (or clearly a secondary button), so two adjacent actions don't read as button-vs-afterthought-text.
4.2 **Primary CTA palette** (`app.css`): the only blue is the "Add Route" button (`#4a90d9`), off the slate/green/red token palette. Either introduce a `--accent` token and apply it consistently, or restyle the button to a neutral-dark/green primary that fits. Keep one primary accent, used once.
4.3 **Native date input** (`add_form.html` / `app.css`): the `dd/mm/yyyy` picker looks unstyled beside the custom text inputs — match border-radius/height/border to `.form-row input`.

### Files
- Modify: `frontend/templates/dashboard.html`, `frontend/templates/partials/add_form.html`, `frontend/static/app.css` (as needed)

### Tests
- NON-REGRESSION only: full suite green; `/` renders 200. No new unit tests (pure styling).
- Manual: visual confirmation in `.agent/reports/012-phase-4.md`.

---

## Handoff notes
- **Read first:** `backend/pages.py::_sparkline` (~154-188) and `get_best_price_series` in `backend/db.py`; `frontend/templates/partials/tracker_card.html`; the `.spark*` / `.card-*` blocks in `frontend/static/app.css`.
- `_sparkline` is pure — Phase 1 is the easy, high-value win and should be done and verified before touching layout.
- The DB already returns full-history series; **do not** add a query for the all-time low — it is `min(series)`, marked by `low_*`.
- Test ownership: the executor must not weaken/modify orchestrator tests **except** the single sanctioned edit named in Task 3.2. New tests go in `tests/test_sparkline.py` (Phase 1) and `tests/test_pages.py` (Phases 2-3).
- Run tests with the project venv: `.venv/bin/python -m pytest …` (the base interpreter lacks the deps).
- Cache-buster: `base.html` currently `app.css?v=020`; bump once per phase that changes CSS (→ 021 → 022 → 023). Don't skip — stale CSS will mask visual changes.

## Proposed CLAUDE.md addition (apply on approval — show diff first)
Append one bullet to "Future me notes": *"Sparkline (plan 012): `_sparkline()` floors the y-band to `MIN_SPAN_FRAC=0.06` of the mean price and centers small ranges, so trivial price moves render near-flat; it marks the all-time low (`low_*`, green, most-recent min) and the current point (`last_*`, trend-colored), and no longer labels the series start. `get_best_price_series` is full history so `min(series)==historical_best_price`. Card depart date uses a card-only `format_card_date` filter (weekday + static `one-way` tag; round-trip is a future feature); `_format_date` is unchanged. `currency_symbol` now returns `€`/`$`/`£` with no trailing space (CHF keeps its space)."* Also update the test-suite count line after the new tests land.
