# Plan 008 — Airline logos in results table + dashboard cards

## Context

The detail results table and dashboard cards currently identify airlines by full text name ("Vueling"). The request: show the airline's **logo** instead. The IATA code needed to fetch a logo is already present in the data — it is the prefix of `flight_number` (`"VY 6201"` → `VY`; multi-leg flights are `+`-joined, e.g. `"VY 6201+IB 5678"`). No new flight-source or schema work is required for the table; the dashboard card needs one new read-only subquery to surface the cheapest flight's `flight_number`.

### Decisions locked with the user
- **Scope**: results table (`partials/results_table.html`) **and** dashboard cards (`partials/tracker_card.html`).
- **Logo source**: kiwi.com CDN — `https://images.kiwi.com/airlines/64/{CODE}.png`. (airhex was rejected: it returns 403 without a paid account hash. Verified live: kiwi serves real PNGs by IATA code with no key.)
- **Cell content**: logo only; full airline name carried as `alt` + `title` for accessibility/hover.
- **Fallback to the airline name** happens in three cases:
  1. **No valid code** (empty/missing `flight_number`, or prefix is not a 2-char IATA designator) — handled server-side: the filter returns `""` and the template renders the name.
  2. **Blacklisted code** — a small, manually-maintained set `LOGO_UNAVAILABLE_CODES` in `pages.py`. When you spot an airline rendering kiwi's generic plane icon, add its code to this set; the filter then returns `""` for it and the name renders. Starts empty.
  3. **CDN blocked/unreachable** — `<img onerror>` hides the image and reveals a sibling name span.
- **Known limitation (accepted)**: kiwi returns HTTP 200 with a *generic* plane icon for unknown-but-valid codes (verified: `XX`/`ZZZ` → `airlines.png`). `onerror` does NOT fire for that, so such airlines show the generic icon until their code is added to the blacklist. This is the trade-off the blacklist exists to manage.

---

## Architecture of the change

**Single source of truth for "what code, if any, to render":** a new module-level filter in `backend/pages.py`:

```python
import re

LOGO_UNAVAILABLE_CODES: set[str] = set()  # IATA codes kiwi serves a generic icon for; add manually

_IATA_RE = re.compile(r"^[A-Z0-9]{2}$")

def _airline_code(flight_number: str | None) -> str:
    """First whitespace-delimited token of flight_number, upper-cased, returned
    only if it is a 2-char IATA designator not on the logo blacklist; else ""."""
    if not flight_number:
        return ""
    token = str(flight_number).strip().split(" ", 1)[0].upper()
    if not _IATA_RE.match(token):
        return ""
    if token in LOGO_UNAVAILABLE_CODES:
        return ""
    return token

_env.filters["airline_code"] = _airline_code
```

**Shared rendering component:** a Jinja macro so the table and the card render identical markup. New file `frontend/templates/partials/macros.html`:

```jinja
{% macro airline_logo(flight_number, name) %}
{% set code = flight_number | airline_code %}
{% if code %}<span class="airline-logo-wrap" title="{{ name }}"><img class="airline-logo" src="https://images.kiwi.com/airlines/64/{{ code }}.png" alt="{{ name }}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='inline'"><span class="airline-fallback" style="display:none">{{ name or code }}</span></span>{% else %}{{ name or "—" }}{% endif %}
{% endmacro %}
```

The macro takes the raw `flight_number` and applies the `airline_code` filter internally, so callers do not duplicate extraction logic.

**Dashboard data:** `get_tracker_summaries` (`backend/db.py:263`) gains one correlated subquery returning the cheapest flight's `flight_number` for the latest snapshot, exposed as `best_flight_number`.

```sql
(SELECT fp.flight_number
   FROM flight_prices fp
  WHERE fp.tracker_id = t.id
    AND fp.snapshot_id = (SELECT id FROM snapshots
                          WHERE tracker_id = t.id
                          ORDER BY searched_at DESC LIMIT 1)
  ORDER BY fp.price ASC LIMIT 1) AS best_flight_number
```

---

## Phase 1 — Code-extraction filter + shared logo macro

Establish the server-side logic and the reusable component. No existing template behavior changes yet (macro not yet wired in).

### Tasks
1.1 Add `re` import, `LOGO_UNAVAILABLE_CODES`, `_IATA_RE`, and `_airline_code` to `backend/pages.py`.
1.2 Register `_env.filters["airline_code"] = _airline_code` next to the existing `format_date` filter registration (`pages.py:53`).
1.3 Create `frontend/templates/partials/macros.html` with the `airline_logo` macro (markup above).
1.4 Confirm the raw `jinja2.Environment` in `pages.py` resolves `{% from "partials/macros.html" import airline_logo %}` given `FileSystemLoader("frontend/templates")` — paths are relative to the templates root.
1.5 Run the new filter edge-case tests; confirm new-behavior tests fail before 1.1 and pass after.

### Files
- Modify: `backend/pages.py`
- Create: `frontend/templates/partials/macros.html`

### Design notes / risks
- IATA airline designators are 2 alphanumeric chars (`VY`, `LH`, `U2`, `6X`). The 2-char rule deliberately rejects the test fixture's `flight_number="123"` (3 chars) and bare numeric flight numbers, so those fall back to the name — preserving today's text rendering for fixture data.
- The macro is on one line to avoid Jinja whitespace leaking into `<td>`; keep it dense.

### What NOT to touch
- `_format_date`, `_split_timestamps`, `_enrich_summaries`, `_build_detail_context` and all route handlers in `pages.py`.
- Any template file except the newly created `macros.html`.
- `db.py`.

### Success criteria (tests that must pass)
- `tests/test_airline_logo.py::test_extracts_iata_code_from_flight_number`
- `tests/test_airline_logo.py::test_extracts_first_carrier_code_from_multileg`
- `tests/test_airline_logo.py::test_uppercases_lowercase_code`
- `tests/test_airline_logo.py::test_strips_surrounding_whitespace`
- `tests/test_airline_logo.py::test_returns_empty_for_empty_string`
- `tests/test_airline_logo.py::test_returns_empty_for_none`
- `tests/test_airline_logo.py::test_returns_empty_for_three_digit_flight_number`
- `tests/test_airline_logo.py::test_returns_empty_for_overlong_token`
- `tests/test_airline_logo.py::test_returns_empty_for_unicode_token`
- `tests/test_airline_logo.py::test_returns_empty_for_blacklisted_code`
- `tests/test_airline_logo.py::test_accepts_alphanumeric_code`

### Verification
```bash
pytest tests/test_airline_logo.py -v
```
Paste full output into `.agent/reports/008-phase-1.md`.

---

## Phase 2 — Results table logo

Wire the macro into the detail results table.

### Tasks
2.1 In `frontend/templates/partials/results_table.html`, add `{% from "partials/macros.html" import airline_logo %}` at the top.
2.2 Replace the Airline cell (`results_table.html:19`, currently `{{ item.flight.airline or "—" }}`) with `{{ airline_logo(item.flight.flight_number, item.flight.airline) }}`.
2.3 Add CSS to `frontend/static/app.css`: `.airline-logo { height: 20px; width: auto; vertical-align: middle; }` and `.airline-logo-wrap { display: inline-flex; align-items: center; }`. Append in one block; do NOT duplicate or reorder existing rules (the file has known duplicate-rule debt — add cleanly at the end of the relevant section).
2.4 Confirm the `Flight` column (`flight_number`) is unchanged — the code prefix still reads naturally there.
2.5 Run page tests; confirm new-behavior tests fail before 2.1–2.2 and pass after, and the non-regression anchor stays green throughout.

### Files
- Modify: `frontend/templates/partials/results_table.html`
- Modify: `frontend/static/app.css`

### Design notes / risks
- HTMX swaps replace `#detail-content` wholesale, so `onerror`-mutated DOM does not leak across swaps.
- `alt` and `title` are autoescaped by the `select_autoescape()` env — airline names with special chars are safe.

### What NOT to touch
- Other columns/rows in `results_table.html`; `price_badge.html`; `detail_page.html`.
- Existing CSS rules (no edits to `.best-price`, `.route`, `.card-body`, etc.).
- `pages.py`, `db.py`.

### Success criteria (tests that must pass)
- NEW: `tests/test_pages.py::test_results_table_renders_kiwi_logo_for_valid_code`
- NEW: `tests/test_pages.py::test_results_table_logo_alt_is_airline_name`
- NON-REGRESSION: `tests/test_pages.py::test_detail_page_contains_results_table_when_snapshot_exists` (existing, must stay green)
- NON-REGRESSION: `tests/test_pages.py::test_results_table_falls_back_to_name_when_code_invalid` (new anchor pinning fixture data `flight_number="123"` → name text, no `<img>`)

### Verification
```bash
pytest tests/test_pages.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/008-phase-2.md`.

---

## Phase 3 — Dashboard card logo

Surface the cheapest flight's airline on each tracker card.

### Tasks
3.1 Add the `best_flight_number` correlated subquery (SQL above) to `get_tracker_summaries` in `backend/db.py:263`.
3.2 In `frontend/templates/partials/tracker_card.html`, add `{% from "partials/macros.html" import airline_logo %}` and render `{{ airline_logo(tracker.best_flight_number, tracker.best_flight_number) }}` in the card header next to the route (name var falls back to the code since the card has no full airline name — acceptable; alt/title show the code).
3.3 Decide placement: inline before/after `.route` in `.card-header` (`tracker_card.html:8`). Keep layout intact; add CSS only if spacing needs it (reuse `.airline-logo` from Phase 2).
3.4 Confirm cards with no snapshot (`best_flight_number IS NULL`) render the existing `—` / no logo without error.
3.5 Run db + page tests; confirm new-behavior tests fail before 3.1 and pass after.

### Files
- Modify: `backend/db.py`
- Modify: `frontend/templates/partials/tracker_card.html`

### Design notes / risks
- The card has no full airline name available (only `flight_number`), so the logo's `alt`/`title` use the code. If a richer name is wanted later, surface `airline` in the same subquery — out of scope now.
- The subquery mirrors the existing `best_price` subquery's snapshot-selection logic; keep them consistent so price and logo refer to the *same* cheapest flight.

### What NOT to touch
- The `best_price`, `previous_best_price`, `last_searched_at`, `recent_alerts` subqueries (only add a new one).
- Card actions/footer, toggle/delete handlers.
- `pages.py` route logic.

### Success criteria (tests that must pass)
- NEW: `tests/test_db.py::test_summary_includes_best_flight_number_of_cheapest_flight`
- NEW: `tests/test_pages.py::test_dashboard_card_renders_logo_for_best_flight`
- FAILURE-MODE: `tests/test_db.py::test_summary_best_flight_number_is_none_without_snapshot`
- NON-REGRESSION: `tests/test_db.py::test_summary_still_returns_min_best_price` (anchor: existing `best_price` value unchanged after adding the subquery)

### Verification
```bash
pytest tests/test_db.py tests/test_pages.py -v
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/008-phase-3.md`.

---

## Phase 4 — End-to-end verification + docs

### Tasks
4.1 Run the full suite: `pytest tests/ -v -k "not slow"` — confirm count is ≥ prior 100 passed plus the new tests, 0 failures.
4.2 Manual smoke: `uvicorn backend.main:app --reload`, run a real search on a tracker (e.g. GVA→BCN), confirm real logos render in the table and the card, and that a flight with no valid code shows the airline name.
4.3 Verify `onerror` fallback by temporarily loading with the network blocked (or point one logo at a 404 path in devtools) — confirm the name span appears.
4.4 Add the CLAUDE.md "Future me" note (see below).
4.5 Capture a screenshot or paste the rendered Airline cell HTML into the report.

### Files
- Modify: `CLAUDE.md` (one note, see below)

### What NOT to touch
- Anything else; this phase is verification + docs only.

### Verification
```bash
pytest tests/ -v -k "not slow"
```
Paste full output + manual-smoke notes into `.agent/reports/008-phase-4.md`.

---

## Test specifications

All new test files / additions, labeled by category. **NEW-BEHAVIOR** and **FAILURE-MODE** tests must fail (for the right reason) before implementation; **NON-REGRESSION** tests must pass against current code before any change.

### `tests/test_airline_logo.py` (new file — Phase 1)
Direct unit tests of the `airline_code` Jinja filter (`backend.pages._airline_code`). This is a registered template extension point with a defined contract, not a private intermediate — testing it directly is the right boundary.

NEW-BEHAVIOR:
- `test_extracts_iata_code_from_flight_number` — `"VY 6201"` → `"VY"`
- `test_extracts_first_carrier_code_from_multileg` — `"VY 6201+IB 5678"` → `"VY"`
- `test_uppercases_lowercase_code` — `"vy 6201"` → `"VY"`
- `test_strips_surrounding_whitespace` — `"  LH 400 "` → `"LH"`
- `test_accepts_alphanumeric_code` — `"U2 8001"` → `"U2"`; and `"6X 100"` → `"6X"`

FAILURE-MODE (edge matrix: empty, null, boundary length, whitespace, unicode):
- `test_returns_empty_for_empty_string` — `""` → `""`
- `test_returns_empty_for_none` — `None` → `""`
- `test_returns_empty_for_three_digit_flight_number` — `"123"` → `""` (off-by-one on the 2-char rule; also pins fixture-data behavior)
- `test_returns_empty_for_overlong_token` — `"ABCDE 1"` → `""`
- `test_returns_empty_for_unicode_token` — `"✈ 100"` → `""`
- `test_returns_empty_for_blacklisted_code` — monkeypatch `pages.LOGO_UNAVAILABLE_CODES = {"ZZ"}`, then `"ZZ 100"` → `""`

### `tests/test_pages.py` (additions — Phases 2 & 3)
Mock boundary = the DB (insert fixtures via existing `create_snapshot` + `insert_flight_prices`, as the current tests already do). Assert on rendered HTML, not internals.

NEW-BEHAVIOR (Phase 2):
- `test_results_table_renders_kiwi_logo_for_valid_code` — insert flight `airline="Vueling", flight_number="VY 6201"`; GET `/trackers/1`; assert `images.kiwi.com/airlines/64/VY.png` in `response.text`.
- `test_results_table_logo_alt_is_airline_name` — same fixture; assert `alt="Vueling"` in `response.text`.

NON-REGRESSION (Phase 2):
- `test_results_table_falls_back_to_name_when_code_invalid` — insert fixture with `airline="XX", flight_number="123"` (matches existing fixtures); GET `/trackers/1`; assert `"XX"` present AND `images.kiwi.com` NOT in text. Confirm this **passes against current code** (current cell already renders `airline`) before changes, and still passes after.
- (existing) `test_detail_page_contains_results_table_when_snapshot_exists` must stay green.

NEW-BEHAVIOR (Phase 3):
- `test_dashboard_card_renders_logo_for_best_flight` — create tracker, snapshot, two flights with different prices, the cheaper having `flight_number="LH 400"`; GET `/`; assert `images.kiwi.com/airlines/64/LH.png` in text.

### `tests/test_db.py` (additions — Phase 3)
NEW-BEHAVIOR:
- `test_summary_includes_best_flight_number_of_cheapest_flight` — two flights (`"VY 6201"` @ 200, `"LH 400"` @ 100) in latest snapshot; assert `summary["best_flight_number"] == "LH 400"`.

FAILURE-MODE:
- `test_summary_best_flight_number_is_none_without_snapshot` — tracker with no snapshot; assert `summary["best_flight_number"] is None`.

NON-REGRESSION:
- `test_summary_still_returns_min_best_price` — same two-flight fixture; assert `summary["best_price"] == 100` (pins that the new subquery did not alter the existing price aggregate). Confirm green before changes if an equivalent anchor exists; otherwise this is a new anchor that must pass immediately after Phase 3's SQL change and is logically independent of it.

### Deliverables (files)
- Plan: `.agent/plans/008-airline-logos.md`
- New test file: `tests/test_airline_logo.py`
- Test additions: `tests/test_pages.py`, `tests/test_db.py`
- Reports: `.agent/reports/008-phase-{1,2,3,4}.md`

---

## Proposed CLAUDE.md addition (Phase 4 — show before applying)

Add under "Future me notes":

> - **Airline logos**: results table and dashboard cards show airline logos from kiwi.com (`images.kiwi.com/airlines/64/{IATA}.png`). The IATA code is extracted from `flight_number`'s prefix by the `airline_code` Jinja filter in `pages.py` (2-char IATA designator only; multi-leg uses the first carrier). Rendering is centralized in the `airline_logo` macro (`templates/partials/macros.html`). kiwi serves a *generic* plane icon (HTTP 200) for unknown codes, so `onerror` can't catch those — add such codes to `LOGO_UNAVAILABLE_CODES` in `pages.py` to force the airline-name fallback. `onerror` still covers a fully blocked CDN.

---

## Handoff notes
- Core logic: `backend/pages.py` (filter + blacklist), `frontend/templates/partials/macros.html` (macro).
- Touch points: `partials/results_table.html:19`, `partials/tracker_card.html:8`, `backend/db.py:263` (`get_tracker_summaries`).
- DB fixtures for tests: `create_snapshot` + `insert_flight_prices` (`db.py:160`, `:176`); `flight_number` column already stored and returned by `get_flight_prices_for_snapshot` (`db.py:233`).
- Live CDN facts (verified 2026-05-31): kiwi `200 image/png` for `VY`/`U2`/`LH`; unknown codes → `200` generic `airlines.png`; airhex → `403` (needs paid hash); daisycon works but wordier URL and also no 404 for unknown.
- Full suite baseline: `pytest tests/ -v -k "not slow"` → 100 passed, 1 deselected.
