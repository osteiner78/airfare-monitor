# Plan 017 — Kayak as a third source inside the main search cycle (browser render + LLM extraction)

> **Revision note (2026-08-04, v2).** v1 of this plan gave Kayak its own
> snapshots on its own APScheduler job. Review against the code found that
> breaks every "latest snapshot" consumer (see "Why Kayak shares the main
> snapshot" below), so Phases 1, 3 and 5 are restructured. v1's Decisions 5
> and 10 are withdrawn. `tests/test_kayak_scheduling.py` was written against
> v1's Phase 3 and is now partly stale — see "Test files to revise before
> implementation".

## Context

`fli` and `fast-flights` (composed today behind `FallbackSource`) both scrape
Google Flights specifically — one via a reverse-engineered batchexecute RPC,
the other via the public search-results URL. They differ in *mechanism*, not
in *inventory*: the tracker can only ever report the lowest price Google
Flights itself chooses to surface. Confirmed non-hypothetical via a live
example (GRU→ZRH 2026-08-21: Google Flights surfaced TP88+TP934 at €711;
Kayak separately surfaced the cheaper TP84+TP934 combination at $785,
absent from Google Flights) and a hand prototype (Playwright render of
`kayak.com/flights/GRU-ZRH/2026-08-21` succeeded on a single request, no
CAPTCHA; the TP84 itinerary was present; extraction needs an LLM parse step
because Kayak's DOM classes are hash-obfuscated and unstable, not because
regex is merely inconvenient).

**Decision: Kayak is a genuine concurrent source** — it contributes to the
same snapshot as fli/fast_flights, on its own slower cadence, rather than
being a fallback engaged only when they come back empty.

**Known reliability constraint** (from a comparable open-source project's
docs, not yet independently re-measured against sustained load): Kayak runs
PerimeterX bot detection, ~40–70% success in burst mode, degrading further
under sustained polling. This plan builds the graceful-degradation and
telemetry needed to *live with* that constraint; tuning the actual
success-rate is explicitly deferred to a follow-up plan (see Decisions).

**Confirmed host resources** (2026-08-04): `minnie` has 6 CPU / 10Gi RAM,
~9.3Gi available, 19G disk free at 60% used — comfortably more than the
`256M/0.5cpu` convention in `/srv/CLAUDE.md` assumed. This directly informs
Phase 5's Docker decisions.

---

## Analysis summary

**Extension points already fit for purpose** — no changes needed:
- `SearchSource` protocol (`backend/sources/base.py:21-30`)
- `FlightResult.source` field (`base.py:7`) and `flight_prices.source` column
  (`db.py:40`) — already exist, already populated by every source
- `last_error` / `last_error_level` convention, read by `search_and_store`
  and logged via `insert_log` — the established graceful-degradation contract
- `create_tracker(**kwargs)` / `update_tracker(**kwargs)` (`db.py:96`,
  `db.py:137`) are generic over columns — a new `trackers` column needs no
  CRUD code change
- `main.py::_startup` already re-registers a job per active tracker on boot —
  because Kayak now rides the main job, it needs no separate re-registration

**Two things assumed to need new plumbing already work:**
1. `get_tracker_summaries`'s `best_price` (`db.py:279-286`) is already
   `MIN(fp.price)` across the whole latest snapshot, source-blind. Kayak
   rows landing in that snapshot already win the summary "cheapest price"
   for free. Only *attribution* (`best_source`) is missing — see Phase 4.
2. `pages.py` already passes full `flight_prices` rows (including `source`)
   into the template context. `results_table.html` just has no `<td>` for
   it — Phase 4's UI work is templating, not plumbing.

### Why Kayak shares the main snapshot (supersedes v1 Decisions 5 and 10)

In this codebase a **snapshot is the unit of "the whole market at time T"**,
and six separate consumers assume that. A Kayak-only snapshot is a *partial*
view that every one of them silently misreads as complete:

- `get_tracker_summaries.best_price` (`db.py:279-286`) = `MIN(price)` over
  the **latest** snapshot. After a Kayak-only run the dashboard price would
  be Kayak's cheapest *only* — when Kayak is pricier than Google (roughly
  half the time) the displayed price jumps up and stays wrong until the next
  main run.
- `previous_best_price` (`LIMIT 1 OFFSET 1`) would compare a Kayak snapshot
  against a Google snapshot, so `_primary_delta`'s trend chip flips
  green/red on **source alternation**, not on price movement.
- `get_best_price_series` (`db.py:357`, `GROUP BY s.id`) → the card
  sparkline becomes a sawtooth between two partial views, and
  `at_all_time_low` fires off whichever source happens to be cheap.
- `_build_detail_context` (`pages.py:322+`): `latest` = Kayak snapshot,
  `previous` = Google snapshot ⇒ **every Google flight renders as "missing"
  and every Kayak flight as "new", every cycle, forever** — on the exact
  page Phase 4 decorates.
- `_evaluate_notifications(min(kayak results))` would evaluate alerts
  against a partial view.

v1's Decision 10 (no snapshot on Kayak failure) correctly identified the
failure path but missed that the *success* path has the same defect, worse
and permanent.

Folding Kayak into `search_and_store` dissolves all of it: a Kayak failure
simply contributes zero rows to a snapshot that still holds fli's rows —
which is exactly how `FallbackSource` failing already behaves. No empty
snapshot, no hidden price, no divergent contract.

The only alternative that preserves independent snapshots is making "latest
snapshot" source-aware everywhere (union of latest-per-source across six
correlated subqueries, `get_best_price_series`, and the detail-page diff).
That is larger than Phases 1+3+4 combined, and is rejected on those grounds.

### The coupling problem, and why Phase 1 exists

`backend/fingerprint.py:5` bakes `source` into `flight_key`'s identity:
`f"{result.source}|{result.airline}|{result.flight_number}|{result.departure_time}"`.
Because `FallbackSource` is mutually exclusive (fast_flights only runs when
fli returns nothing), this has never collided in production. Kayak sharing
a snapshot breaks that assumption *by design*: the first flight Kayak quotes
that fli also quotes would render as a phantom "new" flight plus a phantom
"missing" flight, double in the chart, and double in the filter sidebar's
`window.allFlights`. Phase 1 redefines `flight_key` before Kayak's own code
is written.

**Five last-write-wins / duplicate-row sites become reachable** the moment a
`flight_key` can legitimately repeat within one snapshot. Three are dict
comprehensions over a `ORDER BY price ASC` list
(`get_flight_prices_for_snapshot`), and dict comprehensions are
last-write-wins — ascending price order means the surviving row is the *most
expensive* per key. Two more are duplicate-row problems rather than
dict-overwrite problems. Plus one SQL site. All are listed in Phase 1's
tasks. All are inert until `make_flight_key` changes, which is why they are
fixed in the same phase.

**Existing test coverage to build from:** `tests/test_sources.py`,
`test_fast_flights_source.py`, `test_fallback_source.py` (protocol
conformance + failure-mode patterns to mirror for Kayak). `tests/test_pages.py`
establishes the HTTP-level testing convention (`client` fixture, POST
`/api/trackers`, direct `backend.db` calls to seed snapshots/prices, GET
`/trackers/{id}`, assert on `response.text`) used throughout this plan's new
tests.

**Working tree caveat:** this plan was written against a tree with
uncommitted changes to `backend/db.py` and `backend/pages.py`
(`get_price_history` now takes an optional `flight_keys` filter,
`get_sticky_top_flight_keys` rewritten to a `ROW_NUMBER()` window function,
the history fetch moved below `current_flight_map`). Line numbers below are
approximate — **re-grep before editing**, do not trust a line number blind.

---

## Decisions (confirmed with user, 2026-08-04)

1. **Kayak is a concurrent source sharing the main snapshot**, not a
   fallback and not an independently-snapshotting job. Drives Phases 1 and 3.
2. **Cross-source flight identity: full merge.** `flight_key` drops
   `source`; the same physical flight from any source shares one chart line
   / history row. Required by Decision 1 — with sources sharing a snapshot,
   the phantom new/missing-flight problem is the *expected steady state*,
   not an edge case.
3. **Existing production `flight_key` rows are backfilled** to the new
   3-part format in the same operation as the code change (Phase 1.7).
   Without it, all 160k rows of chart history detach silently.
4. **Opt-in per tracker**, default off. A new `trackers.kayak_enabled`
   column; toggled via a new detail-page control mirroring the existing
   active/pause toggle.
5. **Kayak cadence: independent of the main tick, ~3h base ± 20% jitter**,
   implemented as a persisted `trackers.kayak_next_due_at` due-check
   evaluated on each main-job run, plus a small random pre-render delay.
   Arrival times must not be perfectly regular — that is the pattern
   PerimeterX is built to catch.
6. **LLM: a cheap third-party model via an OpenAI-compatible endpoint**
   (DeepSeek was the working assumption). **The exact model ID, context
   window and per-token pricing are unverified and must be confirmed against
   the provider's live model list at implementation time** — v1 stated them
   as settled fact, they were not. Claude Haiku 4.5 via the Anthropic API is
   an acceptable alternative at this call volume. API key via `.env`
   (`.gitignore` already excludes `.env`).
7. **Currency: force via Kayak URL params** to match the tracker's
   configured currency — no conversion math needed downstream.
8. **Success bar for this plan:** correct extraction when a check succeeds
   + visible failure logging when it doesn't. No hard uptime target —
   Kayak's reliability tuning is explicitly a follow-up plan.
9. **Explicitly out of scope:** Skyscanner implementation (pipeline built
   source-agnostic so it *can* reuse this shape later, no Skyscanner code
   now), booking/purchase flow, the bot-detection tuning experiment itself
   (this plan ships defaults + the telemetry needed to run that experiment).
10. **Accepted tradeoff — Kayak's ToS prohibit automated access**;
    PerimeterX is the enforcement mechanism. One request per ~3h per opted-in
    tracker, for personal use, is the deliberate risk being taken. It is
    also the reason not to raise the cadence later.
11. **Chromium is bundled into the main container**, not a sidecar
    (justified by the confirmed 6 CPU/10Gi headroom). The accepted cost:
    a Chromium OOM takes the API down with it, so Phase 5 sizes limits
    generously and fixes `shm_size`.

---

## Phase 1 — Foundation: source-independent `flight_key`, dedup-safe chart inputs, history backfill

### Intent
Redefine flight identity to be source-independent, fix the five sites that
become reachable once a `flight_key` can repeat within a snapshot, and
migrate the 160k existing production rows to the new key format — verified
against the *existing* fli/fast_flights system, before Kayak's own code
exists. This isolates the highest-blast-radius change in this plan (it
touches chart lines, price history, the missing-flight diff, and the filter
sidebar's data feed) from the new source's complexity, so a regression here
is unambiguously this phase's fault.

### Tasks
1.1 `backend/fingerprint.py`: change `make_flight_key` to
    `f"{result.airline}|{result.flight_number}|{result.departure_time}"`
    (drop `source`, 3 parts instead of 4).
1.2 `pages.py` `previous_prices` (~`:338`): replace the dict comprehension
    with a **first-write-wins** loop (`setdefault`) so the *cheapest* price
    per `flight_key` survives. `get_flight_prices_for_snapshot` already
    returns `ORDER BY price ASC`, so no extra sort/min pass is needed.
1.3 `pages.py` `prev_flights` (~`:339`): same `setdefault` fix, so a
    reconstructed "missing" flight shows its cheapest historical quote.
1.4 `pages.py` `current_flight_map` (~`:385-389`): same `setdefault` fix for
    the current-snapshot label/lookup map.
1.5 `pages.py` `ordered_top_keys`: currently slices
    `flights_with_delta[:top_n]` — that slices **rows, not distinct keys**,
    so a duplicated key consumes two of the `top_n` colour slots. Build the
    list by walking `flights_with_delta` in order and appending each key
    only the first time it is seen, stopping at `top_n` **distinct** keys.
1.6 `pages.py` `all_flights` (the `window.allFlights` feed): currently
    appends one entry per row, so a duplicated key double-enters
    `filters.js`'s client-side price-rank top-N. Dedupe by `flight_key`,
    keeping the cheapest row per key. **This is chart input, not the results
    table** — the two must not be conflated (see 1.8).
1.7 `backend/db.py` `get_sticky_top_flight_keys`: the `ROW_NUMBER() OVER
    (PARTITION BY fp.snapshot_id ORDER BY fp.price ASC)` window gives
    duplicate keys separate rank slots, so `rn <= top_n` can yield fewer
    than `top_n` distinct flights. Rank over a per-snapshot deduped set
    instead — e.g. rank the rows of
    `SELECT snapshot_id, flight_key, MIN(price) AS price FROM flight_prices
     WHERE tracker_id = ? GROUP BY snapshot_id, flight_key`.
1.8 Confirm `current_keys` (a `set`) and `results_table.html`'s render loop
    need **no** change: set membership already collapses duplicate keys for
    the missing-flight diff, and the results table showing one `<tr>` per DB
    row is a *feature* (multi-source transparency — the user explicitly
    asked to see every source's quote). No code change expected; pinned by
    `test_results_table_shows_every_source_row_even_when_flight_key_repeats`.
1.9 **Production data backfill — requires explicit user confirmation before
    running** (per this project's CLAUDE.md: altering data needs sign-off).
    Verified state of the live DB on 2026-08-04: 159,973 rows, source values
    `google_flights` (159,784) and `fast_flights` (189), all keys in the
    4-part format. Neither source name contains `|`, so stripping the first
    segment is unambiguous.
    ```bash
    docker compose stop
    cp data/airfare.db data/airfare.db.bak-017        # 183MB, 19G free
    sqlite3 data/airfare.db \
      "UPDATE flight_prices SET flight_key = substr(flight_key, instr(flight_key, '|') + 1);"
    docker compose start
    ```
    Without this, on the first search after deploy every chart line resets to
    a single point, every flight reports as `"new"`, and
    `get_sticky_top_flight_keys` returns old-format keys that no longer match
    `current_flight_map` (labels silently fall back to the raw key string).
    None of that raises an error — it is invisible unless looked for.
    Bonus: the backfill merges those 189 `fast_flights` rows into their
    Google counterparts, which is exactly the intent of Decision 2.

### Files
- Modify: `backend/fingerprint.py`, `backend/pages.py` (four sites),
  `backend/db.py` (`get_sticky_top_flight_keys`)
- Operational: live `data/airfare.db` (1.9, gated on confirmation)
- Already written for this plan: `tests/test_fingerprint.py` (revised in
  place), `tests/test_pages_multi_source.py` (needs the additions below)

### What NOT to touch
- `results_table.html`, `charts.js`, `filters.js` — no template/JS changes
  in this phase; Phase 1 is backend identity + chart-input dedup only.
- `get_price_history` — operates on `flight_key` as an opaque string; no
  change needed once `make_flight_key` produces source-independent values.

### Design decisions / open questions / risks
- **Risk:** another undiscovered duplicate-key site. Mitigation: re-run
  `grep -n 'flight_key' backend/pages.py backend/db.py backend/*.py` during
  implementation and audit every hit against "what happens if this key
  appears twice in one snapshot" — v1 of this plan found three sites and
  missed two, so treat the list above as a floor, not a ceiling.
- **Risk:** 1.9 is irreversible in-place. The `cp` backup is the mitigation
  and is not optional.
- **Decision:** the results table intentionally does *not* dedupe
  same-`flight_key` rows — full transparency was explicitly requested ("a
  column... so the user can look for that price manually").

### Tests
**`tests/test_fingerprint.py`** (revised in place, already written):
- NON-REGRESSION (pass now, must keep passing):
  `test_same_flight_result_produces_same_key_on_repeated_calls`,
  `test_different_departure_times_produce_different_keys`,
  `test_flight_key_still_differs_for_genuinely_different_flights_from_same_source`,
  `test_key_with_empty_airline_and_flight_number_still_differs_by_departure_time`
- NEW BEHAVIOR (fail now, pass after 1.1):
  `test_nonstop_key_contains_three_pipe_separated_parts`,
  `test_nonstop_key_does_not_start_with_source_name`,
  `test_nonstop_key_contains_airline_and_flight_number`,
  `test_multistop_key_joins_airlines_with_plus`,
  `test_multistop_key_joins_flight_numbers_with_plus`,
  `test_flight_key_identical_across_different_sources_for_same_physical_flight`
  (the core point of this phase),
  `test_key_with_empty_airline_still_produces_three_parts`

**`tests/test_pages_multi_source.py`** (already written):
- NON-REGRESSION: `test_flight_not_marked_missing_when_still_quoted_by_a_different_source`,
  `test_results_table_shows_every_source_row_even_when_flight_key_repeats`
- FAILURE MODE (fail now, pass after 1.2-1.3):
  `test_price_delta_uses_cheapest_previous_price_when_flight_key_quoted_by_two_sources`,
  `test_missing_flight_reconstruction_uses_cheapest_historical_price`

**Added to `tests/test_pages_multi_source.py`** for 1.5-1.6 (the two sites v1
missed), all confirmed failing first:
- `test_window_all_flights_has_one_entry_per_flight_key`
- `test_window_all_flights_entry_uses_cheapest_price_for_a_duplicated_key`
- `test_chart_top_n_counts_distinct_flights_not_rows` (asserts colour rank
  follows price rank over *distinct* flights: cheapest → `CHART_COLORS[0]`,
  second → `[1]`, third → `[2]`)

**Added to `tests/test_chart_data.py`** for 1.7 (it sits with the existing
sticky-key tests rather than in a new file):
- `test_get_sticky_top_flight_keys_returns_top_n_distinct_flights_when_a_key_repeats_in_a_snapshot`

### Success criteria
All tests in `tests/test_fingerprint.py` and `tests/test_pages_multi_source.py`
pass, plus the four added above. Full suite green. **And**, after 1.9: load
a real tracker's detail page and confirm chart lines still span the full
history rather than starting from a single point.

### Verification
```bash
pytest tests/test_fingerprint.py tests/test_pages_multi_source.py -v -k "not slow"
pytest tests/ -v -k "not slow"   # full non-regression pass
sqlite3 data/airfare.db "SELECT flight_key FROM flight_prices LIMIT 3;"  # post-backfill: 3 parts, no source prefix
```
Paste full output — plus a note on the detail-page chart-continuity check —
into `.agent/reports/017-phase-1.md`.

---

## Phase 2 — `backend/sources/kayak.py`: Playwright render + LLM extraction

### Intent
A self-contained `SearchSource` implementation, structured as four swappable
seams — `_build_url` (pure), `_render` (Playwright boundary), `_extract`
(LLM boundary), `_validate` (pure) — so the pipeline shape is reusable for a
future Skyscanner source without copying browser/LLM plumbing, while this
phase implements Kayak only.

Two design decisions matter most. **First: bot detection is checked before
spending an LLM call** — `_render` returns raw text, a pure `_looks_blocked`
check runs first, and `_extract` is only invoked once that check passes.
A blocked run stays cheap and `_looks_blocked` stays trivially unit-testable
without mocking a browser. **Second: extracted prices are grounded against
the rendered text before they are trusted** — see 2.7. An LLM reading a
~100KB text dump will occasionally invent or mis-associate a number, and a
hallucinated cheap price is *permanent* damage: `historical_best_price` is
`MIN` over all rows and is never recomputed, and the bad price fires a
notification on its way in.

Out of scope: wiring into the scheduler (Phase 3), DB/UI changes (Phase 4).
This phase produces a source that satisfies `SearchSource` in isolation.

### Tasks
2.1 Add `playwright` (**version-pinned** — see Phase 5.1 for why) and the
    OpenAI-compatible client library to `requirements.txt`.
2.2 `KayakSource.__init__`: same `last_error` / `last_error_level` pattern
    as every other source.
2.3 `KayakSource._build_url(origin, dest, depart_date, currency) -> str`
    (`@staticmethod`, pure): construct
    `https://www.kayak.com/flights/{origin}-{dest}/{depart_date}?sort=price_a&currency={currency}`
    or Kayak's actual currency/locale param — **confirm the real param name
    during implementation** against a non-USD tracker; the prototype ran
    USD-default and never exercised it.
2.4 `KayakSource._looks_blocked(body_text: str) -> bool` (`@staticmethod`,
    pure): checks for known bot-detection markers (CAPTCHA / "verify you are
    human" / "unusual traffic" / block-page text — start from the marker
    list used in the hand prototype, expand from real runs).
2.5 `KayakSource._render(url: str) -> str` (Playwright boundary, async):
    launch headless Chromium, navigate, wait for results to stabilize.
    **Do not use `[data-resultid]` or any other single guessed CSS
    selector** — the hand prototype proved that selector wrong against real
    markup and confirmed Kayak's class names are hash-obfuscated
    (`mZv3`, `JjjA`, `wRhj`, unstable across deploys). Poll the count of the
    `"Select"` button text in the body instead (once per result row, stable
    in the prototype) until it stops changing, capped at ~45s. Return
    `page.inner_text("body")`.
    **Lifecycle:** use `async with async_playwright()` plus `try/finally
    browser.close()`. This service runs under `uvicorn --reload`, and
    `/srv/airfare-monitor/CLAUDE.md` already documents reload orphaning a
    mid-work process; Chromium is a heavier variant of the same trap.
2.6 `KayakSource._extract(body_text, top_n) -> list[dict]` (LLM boundary,
    async): call the model with a structured-output/tool schema requesting
    up to `top_n` flights as `{airline, flight_number, departure_time,
    arrival_time, duration_min, stops, price}`. **Explicit request timeout.**
    Raise on a malformed/unparseable response — don't silently return
    partial data from a response that failed schema validation.
2.7 `KayakSource._validate(rows, body_text) -> list[dict]` (`@staticmethod`,
    pure) — **the grounding check**. For each extracted row:
    - drop it unless its price appears **literally in `body_text`** (compare
      against a small set of renderings: bare integer, thousands-separated,
      with and without the currency symbol — derive the set from what the
      prototype's captured text actually contains, don't guess);
    - drop it if `price <= 0`;
    - drop it if the price is absurdly outside the band of the other
      extracted rows (e.g. >10x the median of the surviving set).
    Log a `WARNING` naming each dropped row. This is a pure function over
    two strings — cheap to run and cheap to test.
2.8 `search()`: short-circuit and return `[]` without rendering when
    `top_n <= 0`. Otherwise: build URL → `_render` → `_looks_blocked`
    (if true: `last_error_level = "WARNING"`, log mentioning bot detection,
    return `[]` **without** calling `_extract`) → `_extract` → `_validate`
    → map each surviving dict to a `FlightResult` with `source="kayak"` and
    `currency` from the request (not re-parsed from the page).
    `booking_url`: the constructed Kayak search URL itself (same precedent
    as `fast_flights.py`'s `query.url()` — Kayak's list view has no per-row
    deep link without a click-through).
    Wrap the whole body in an **overall wall-clock cap** so a hung render
    plus a hung LLM call can't exceed the budget the caller assumes.
2.9 Exception handling: wrap `_render`/`_extract`/`_validate` so *any*
    exception sets `last_error`/`last_error_level = "ERROR"` and returns
    `[]` — mirrors every other source's "never raises" contract. **Scrub the
    API key from the error string** before it reaches `last_error`: it is
    written to `system_logs` and rendered on `/monitor`, and client
    exceptions can carry request context.
2.10 `_map_result`: tolerate missing optional fields (`duration_min`,
    `stops`) by defaulting to `None` rather than raising `KeyError` — the
    JSON schema should make them optional, and `_map_result` shouldn't trust
    that it always will be.
2.11 Read the API key via `os.environ[...]` **at call time**, not import
    time, so a missing key surfaces as a clean `last_error` rather than an
    import-time crash that takes the whole app down.

### Files
- New: `backend/sources/kayak.py`
- Modify: `requirements.txt`
- Already written for this plan: `tests/test_kayak_source.py` (needs the
  `_validate` additions below)

### What NOT to touch
- `backend/sources/__init__.py::get_sources()` — that list is global, not
  per-tracker, and Kayak is opt-in per tracker. It is called directly from
  `search_and_store` in Phase 3, never registered here.
- `backend/sources/fallback.py`, `fast_flights.py`, `google_flights.py` —
  untouched; Kayak is a peer, not nested inside `FallbackSource`.

### Design decisions / open questions / risks
- **Open question:** the real Kayak currency/locale URL parameter (2.3).
- **Open question:** the exact model ID and its structured-output support
  (Decision 6) — verify against the provider's live model list, do not
  carry v1's numbers forward.
- **Risk:** structured output may format oddly for codeshare rows
  ("TAP AIR PORTUGAL, easyJet") or 2+ layover itineraries. Mitigated by
  2.6's raise-on-malformed and 2.7's grounding check.
- **Risk:** `_looks_blocked`'s marker list is necessarily incomplete —
  PerimeterX wasn't exhaustively probed. Expect to expand it from real logs;
  that's maintenance, not a defect. Note the silent variant: a page that
  renders zero results *without* a CAPTCHA marker falls through to
  `_extract` returning `[]`, which is handled as "no flights found"
  (`WARNING`), not as a block.

### Tests
`tests/test_kayak_source.py` (already written, currently failing with
`ModuleNotFoundError` as expected):
`test_kayak_source_satisfies_search_source_protocol`,
`test_build_url_includes_origin_destination_and_date`,
`test_build_url_sorts_by_cheapest_price`,
`test_build_url_encodes_requested_currency`,
`test_looks_blocked_true_when_captcha_marker_present`,
`test_looks_blocked_false_for_normal_results_page`,
`test_looks_blocked_false_for_empty_string`,
`test_search_returns_flight_results_mapped_from_extraction`,
`test_search_sets_source_field_to_kayak_on_every_result`,
`test_search_result_currency_matches_requested_currency`,
`test_search_returns_empty_list_and_error_when_render_raises`,
`test_search_returns_empty_list_and_warning_when_blocked_markers_detected`
(also asserts the extraction mock is *not* called — pins 2.8's ordering),
`test_search_returns_empty_list_and_error_when_extraction_raises`,
`test_search_returns_empty_list_and_warning_when_extraction_finds_no_flights`,
`test_search_with_top_n_zero_returns_empty_list_without_rendering`,
`test_search_never_raises_for_unexpected_exception_type`,
`test_search_maps_result_with_missing_optional_fields_without_crashing`.

**Added for 2.7 / 2.9**, all confirmed failing first:
- `test_validate_drops_row_whose_price_is_absent_from_body_text`
- `test_validate_keeps_row_whose_price_appears_thousands_separated`
  (Kayak renders four-digit fares as `€1,204` — a naive `str(price) in body`
  check would drop every expensive itinerary as hallucinated)
- `test_validate_drops_non_positive_price`
- `test_validate_drops_price_wildly_outside_the_band_of_other_rows`
- `test_search_drops_hallucinated_price_not_present_in_rendered_text`
  (pins that `_validate` is *wired into* `search()`, not merely importable)
- `test_error_message_does_not_contain_api_key` (sets `DEEPSEEK_API_KEY` to a
  sentinel — rename if 2.11 settles on a different env var)

**Note for the implementer:** the v1 `_render` mocks returned the stub string
`"<rendered page text>"`, which contains no price and which the new grounding
check would therefore correctly reject, failing four otherwise-valid tests.
They now return `_sample_body()`. If you change `_validate`'s matching rules,
change `_sample_body()` with them.

Plus `@pytest.mark.slow test_real_kayak_search_returns_results_for_valid_route`
(live network + real Chromium + real API key — run manually, deselected by
default like the other sources' live tests).

### Success criteria
All non-slow tests in `tests/test_kayak_source.py` pass; the `slow` test
passes when run manually with real credentials.

### Verification
```bash
pytest tests/test_kayak_source.py -v -k "not slow"
pytest tests/test_kayak_source.py -v -m slow   # manual, needs API key + Chromium
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/017-phase-2.md`.

---

## Phase 3 — Wire Kayak into the main search cycle

### Intent
Make Kayak checks opt-in per tracker and independently paced, **while
contributing to the same snapshot as fli/fast_flights** (see "Why Kayak
shares the main snapshot"). The central design decision: `search_and_store`
gains one conditional Kayak call gated by a persisted due-check, and
everything downstream — snapshot creation, `insert_flight_prices`,
`_evaluate_notifications`, the `search_done` log — stays exactly as it is,
operating on a `results` list that now may contain rows from three sources.
A Kayak failure degrades to "zero extra rows", identical to how a
`FallbackSource` failure already behaves.

Out of scope: the UI changes that make the opted-in state visible beyond a
bare toggle (Phase 4); the Docker changes needed to actually run this in
production (Phase 5).

### Tasks
3.1 `backend/db.py` `_SCHEMA`: add to the `trackers` table
    `kayak_enabled INTEGER NOT NULL DEFAULT 0` and
    `kayak_next_due_at TEXT` (nullable; NULL = never attempted = due now).
    This covers fresh DBs, including every test via the `db_path` fixture.
    **Does not** retrofit the live DB — `CREATE TABLE IF NOT EXISTS` no-ops
    against an existing table. Manual migration, **explicit user
    confirmation required** (this project's CLAUDE.md gates schema changes):
    ```bash
    sqlite3 data/airfare.db \
      "ALTER TABLE trackers ADD COLUMN kayak_enabled INTEGER NOT NULL DEFAULT 0;
       ALTER TABLE trackers ADD COLUMN kayak_next_due_at TEXT;"
    ```
    `create_tracker`/`update_tracker` are `**kwargs`-generic — no CRUD code
    change needed.
3.2 `backend/scheduler.py`: add `_jittered_kayak_interval_minutes(base_minutes)`
    (pure) — returns `base_minutes` randomized within ±20%, floored so tiny
    bases can't go non-positive. Document in the docstring that the *why* is
    bot-detection mitigation: perfectly regular polling is what PerimeterX
    is built to catch.
3.3 `backend/scheduler.py`: add `_kayak_due(next_due_at: str | None, now: datetime) -> bool`
    (pure) — `True` when `next_due_at` is `None` or `now >= next_due_at`.
    Keeping this pure keeps the cadence logic testable without a scheduler.
3.4 `backend/scheduler.py` `search_and_store`: after the existing
    `get_sources()` loop and **before** `create_snapshot`, add a Kayak
    block, guarded by `tracker["kayak_enabled"]` and `_kayak_due(...)`:
    - optional small random pre-render delay (0–15 min,
      `asyncio.sleep`) so arrival times aren't snapped to the main tick
      grid. Skippable via a `delay: bool = True` parameter on
      `search_and_store` so Phase 6's manual trigger doesn't wait.
    - `results.extend(await KayakSource().search(...))`
    - on `last_error`, `insert_log(level, "kayak_search_error", ...)` —
      distinct event name from the main loop's `search_error` so `/monitor`
      can be filtered.
    - **always** write `kayak_next_due_at = now + _jittered_kayak_interval_minutes(base)`
      via `update_tracker`, on success *and* failure, so a blocked run can't
      hot-retry on the next main tick.
    - wrap in `try/except` so a Kayak failure can never prevent the snapshot
      from being written with fli's rows.
    Base interval: reuse `tracker["interval_minutes"]` (default 180 = the
    desired 3h) — no new user-facing interval setting.
3.5 `backend/sources/__init__.py`: **unchanged.** `get_sources()` is global
    and unconditional; Kayak is per-tracker opt-in, so it is constructed
    directly inside `search_and_store`. Leave a one-line comment saying so,
    so the next reader doesn't "fix" the omission.
3.6 `backend/models.py`: add `kayak_enabled: bool | None = None` to
    `TrackerUpdate` (which currently carries only `active` and
    `interval_minutes`), and `kayak_enabled: bool` to `TrackerResponse`.
3.7 `backend/api.py`: confirm `update_tracker_endpoint` (`PATCH
    /trackers/{tracker_id}`, already generic over `TrackerUpdate`'s fields)
    accepts `kayak_enabled` with no code change — verify, don't assume.
3.8 `backend/pages.py`: add `PATCH /trackers/{tracker_id}/toggle-kayak`
    mirroring `toggle_tracker_detail`: flip `kayak_enabled`, log
    `"kayak_enabled"`/`"kayak_disabled"`, re-render
    `partials/detail_page.html`. **No job scheduling calls** — there is no
    separate Kayak job any more; enabling the flag is sufficient, and
    `kayak_next_due_at` being NULL makes the first check due immediately.
    Add a small toggle control to the detail page template alongside the
    existing active/pause toggle — detail page only, not the dashboard card.
3.9 **No `main.py` change needed.** `_startup` already re-registers a job
    per active tracker, and Kayak now rides that job. (v1 flagged this as an
    open question; folding into the main job answers it.)

### Files
- Modify: `backend/db.py` (`_SCHEMA`), `backend/scheduler.py`,
  `backend/models.py`, `backend/pages.py`,
  `frontend/templates/partials/detail_page.html`,
  `backend/sources/__init__.py` (comment only)
- Operational: live DB `ALTER TABLE` (3.1, gated on confirmation)
- Already written for this plan: `tests/test_kayak_scheduling.py` (rewritten
  for this design — see below)

### What NOT to touch
- `create_snapshot` / `insert_flight_prices` / `_evaluate_notifications`
  call sites — they operate on the combined `results` list unchanged. That
  is the whole point of the fold-in.
- `FallbackSource` and the `get_sources()` loop — Kayak sits beside it, not
  inside it.
- Dashboard card / `tracker_card.html` — detail-page only, per 3.8.

### Design decisions / open questions / risks
- **Consequence, accepted:** Kayak's cadence is quantized to
  `interval_minutes`. At the default 180 min that is exactly the 3h target;
  jittered `kayak_next_due_at` lands either on the next tick or the one
  after, so effective spacing varies between ~3h and ~6h. The pre-render
  delay (3.4) supplies sub-grid irregularity. If a tracker runs a much
  longer `interval_minutes`, Kayak inherits it — note it, don't engineer
  around it now.
- **Consequence, accepted:** a Kayak render (~45s) plus an LLM call now sits
  inside the main job's runtime, so a search that took ~5s takes ~1-2 min on
  Kayak ticks. Fine on a 3h interval with one async worker.
- **Risk:** job stacking if a render hangs. Set `max_instances=1`,
  `coalesce=True` and a `misfire_grace_time` on the tracker jobs
  (`add_tracker_job`) so a slow run can't pile up behind itself.
- **Deferred:** exponential backoff on repeated Kayak blocks. The fixed
  jittered interval is the v1 behavior; backoff belongs to the reliability
  follow-up plan.

### Tests
`tests/test_kayak_scheduling.py` has been **rewritten** for this design (10 of
v1's 15 tests targeted `kayak_search_and_store` / `add_kayak_job` /
`remove_kayak_job`, which this revision deletes). The file header records
what was dropped and why.

Surviving from v1, unchanged (5): `test_create_tracker_defaults_kayak_enabled_to_false`,
`test_tracker_kayak_enabled_can_be_turned_on`,
`test_jittered_kayak_interval_stays_within_documented_bounds`,
`test_jittered_kayak_interval_is_not_always_the_same_value`,
`test_jittered_kayak_interval_handles_small_base_without_going_non_positive`.

Replacing the other 10 (14 tests):
- `test_kayak_next_due_at_defaults_to_null`
- `test_kayak_due_when_next_due_at_is_null`
- `test_kayak_due_when_now_is_past_next_due_at`
- `test_kayak_not_due_when_now_is_before_next_due_at`
- `test_search_and_store_puts_kayak_and_fli_results_in_the_same_snapshot`
  (**the core assertion of this phase**)
- `test_snapshot_results_count_includes_both_sources`
- `test_search_and_store_does_not_call_kayak_when_kayak_disabled`
- `test_search_and_store_does_not_call_kayak_when_not_due`
- `test_search_and_store_advances_next_due_at_after_a_successful_kayak_run`
- `test_search_and_store_advances_next_due_at_after_a_failed_kayak_run`
  (no hot-retry)
- `test_kayak_failure_still_stores_fli_results_and_creates_snapshot`
- `test_kayak_failure_logs_kayak_search_error_at_its_own_level`
- `test_kayak_exception_never_propagates_out_of_search_and_store`
- `test_notifications_evaluate_against_cross_source_minimum_price`
  (Kayak cheaper than fli ⇒ the alert fires on Kayak's price)

Add during implementation (they depend on 3.8's exact route/template shape):
- `test_toggle_kayak_endpoint_flips_kayak_enabled`
- `test_toggle_kayak_endpoint_returns_404_for_missing_tracker`

### Success criteria
All tests in the rewritten `tests/test_kayak_scheduling.py` pass, plus the
two toggle endpoint tests.

### Verification
```bash
pytest tests/test_kayak_scheduling.py -v -k "not slow"
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/017-phase-3.md`.

---

## Phase 4 — Query layer + UI: `best_source` attribution and the Source column

### Intent
Surface which source produced the cheapest price, and show every source's
quote transparently in the results table — the two things actually
requested. Mirror `best_flight_number`'s existing correlated-subquery
pattern exactly rather than restructuring `get_tracker_summaries`: that
pattern is proven, already index-backed (`idx_prices_snapshot_price`), and
this plan should not reshape a performance-sensitive query more than
necessary. Because Phase 3 puts all sources in one snapshot, "cheapest
source in the latest snapshot" is now a genuine cross-source comparison
rather than "whichever source happened to run last".

Out of scope: dashboard card changes (the ask was specifically about flight
details).

### Tasks
4.1 `backend/db.py` `get_tracker_summaries`: add a `best_source` correlated
    subquery immediately after `best_flight_number`, identical in shape but
    selecting `fp.source`:
    ```sql
    (SELECT fp.source
     FROM flight_prices fp
     WHERE fp.tracker_id = t.id
       AND fp.snapshot_id = (SELECT id FROM snapshots
                              WHERE tracker_id = t.id
                              ORDER BY searched_at DESC LIMIT 1)
     ORDER BY fp.price ASC, fp.source ASC LIMIT 1
    ) AS best_source,
    ```
    Note the `fp.source ASC` tiebreak: with sources sharing a snapshot, two
    sources quoting the same flight at the same price is the *expected*
    case, and a bare `ORDER BY price LIMIT 1` picks nondeterministically —
    the dashboard would flip attribution between identical runs.
4.2 `backend/pages.py`: add a `source_label` Jinja filter (registered
    alongside `currency_symbol`/`airline_code`) mapping raw values to
    display labels: `"google_flights"` → `"Google Flights"`,
    `"fast_flights"` → pick something that reads clearly (it has never been
    user-facing before), `"kayak"` → `"Kayak"`. Unknown values fall back to
    the raw string — don't raise on an unmapped source.
4.3 `frontend/templates/partials/results_table.html`: add a
    `<th>Source</th>` header and a `<td>{{ item.flight.source | source_label }}</td>`
    cell. The `source` field is already in `item.flight` — templating only,
    no context-building change.
4.4 Confirm `item.flight.source` is never `None`/missing for a "missing"
    (previous-snapshot-reconstructed) row — `prev_flights` (fixed in Phase
    1) carries the full original row dict including `source`. Verify with
    the tests, don't assume.

### Files
- Modify: `backend/db.py` (`get_tracker_summaries`), `backend/pages.py`
  (new filter), `frontend/templates/partials/results_table.html`
- Already written for this plan: `tests/test_best_source.py`

### What NOT to touch
- `tracker_card.html` / dashboard card — no source indicator there.
- `get_best_price_series`, `get_sticky_top_flight_keys` — the chart data
  feed is unaffected; source attribution is a summary/detail concern here.

### Design decisions / open questions / risks
- **Open question:** the display label for `fast_flights` (4.2) — it has
  been an invisible internal fallback until now.

### Tests
`tests/test_best_source.py` (already written, currently failing with
`KeyError: 'best_source'` and template assertions):
`test_get_tracker_summaries_best_source_matches_cheapest_price_row`,
`test_get_tracker_summaries_best_source_updates_when_a_cheaper_source_appears`,
`test_get_tracker_summaries_best_source_is_none_when_no_snapshots`,
`test_results_table_shows_source_for_each_flight_row`,
`test_results_table_source_label_falls_back_to_raw_value_for_unknown_source`.

**Added for 4.1's tiebreak** (inserts the same tie in both orders against two
trackers and asserts both yield `google_flights`):
- `test_best_source_is_deterministic_when_two_sources_tie_on_price`

### Success criteria
All tests in `tests/test_best_source.py` pass.

### Verification
```bash
pytest tests/test_best_source.py -v -k "not slow"
pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/017-phase-4.md`.

---

## Phase 5 — Docker/infra: Chromium in the main container, shm, limits, secrets

### Intent
Get Kayak actually runnable on `minnie`. Bundling Chromium into the existing
container (Decision 11) keeps deployment consistent with the Active-dev
live-reload workflow — a sidecar would need its own reload/restart story
that doesn't fit `--reload-dir backend`. The accepted cost is blast radius:
**Chromium and the API share a cgroup, so a Chromium OOM kills the API too.**
That makes the two limits below load-bearing, not cosmetic.

Out of scope: enabling Kayak on any real tracker (Phase 6).

### Tasks
5.1 `Dockerfile`: after `pip install -r requirements.txt`, add
    `RUN playwright install --with-deps chromium` (the command the hand
    prototype used successfully — pulls Chromium plus system libs via apt in
    one step on `python:3.12-slim`). Browsers land in
    `/root/.cache/ms-playwright`, **outside** the `.:/app` bind mount, so a
    `playwright` pip upgrade that bumps the browser revision silently
    requires an image rebuild — hence the version pin in 2.1.
5.2 `docker-compose.yml`: **add `shm_size: 1gb`.** Verified current state:
    `docker inspect` reports `ShmSize=67108864` (Docker's 64MB default).
    64MB `/dev/shm` is the single most common cause of Chromium crashing in
    containers. (`--disable-dev-shm-usage` on the browser launch is an
    acceptable alternative; doing both is fine.)
5.3 `docker-compose.yml`: raise `deploy.resources.limits`. Verified these
    are **actually applied** by this host's compose version — `docker
    inspect` reports `Memory=268435456` (256M) and `NanoCpus=500000000`
    (0.5) right now, so the current cap is real and Chromium would OOM-kill
    the container. Size from a measured run (`docker stats` during a live
    Kayak render), not a guess; ~`1.5G`/`2.0` cpus is the starting
    hypothesis given 6 CPU / ~9.3Gi free and two other services on the host.
5.4 `docker-compose.yml`: add `env_file: .env` — the first secret this
    project has needed; no `env_file:` directive exists yet.
5.5 Create `/srv/airfare-monitor/.env` (already gitignored) with the LLM API
    key — **do this together with the user**, who holds the key. Do not
    write a placeholder into any committed file.
5.6 Confirm image size / build time growth is acceptable (Chromium + deps
    ≈ 300-400MB against 19G free); check `docker images` before/after.
5.7 Update `/srv/CLAUDE.md`'s Docker conventions: the `256M/0.5cpu` default
    is stale for anything running a browser, and `shm_size` is a required
    consideration for such services. Also add a future-me note to
    `/srv/airfare-monitor/CLAUDE.md` about Playwright + `--reload` orphaning
    Chromium processes (2.5).

### Files
- Modify: `Dockerfile`, `docker-compose.yml`, `/srv/CLAUDE.md`,
  `/srv/airfare-monitor/CLAUDE.md`
- New: `.env` (not committed — created interactively with the user)

### What NOT to touch
- `family-activities`, `atlas-helvetica` compose files — no changes to other
  services' allocations in this plan, even though the same host-resource
  discovery informs them. Separate work.

### Design decisions / open questions / risks
- **Risk:** first container in this project needing system-level apt deps at
  build time. Confirm `playwright install --with-deps` doesn't hit the
  `dpkg was interrupted` issue seen during the hand prototype (pre-existing
  host state, fixed via `dpkg --configure -a`, but worth a clean-build check).
- **Open question:** the exact limit numbers (5.3) — start from an observed
  measurement.

### Tests
No new pytest files — infra, verified operationally, matching the precedent
set by plan 016's Phase 3.

### Success criteria
`docker compose up -d --build` succeeds; container reaches `healthy`;
Chromium launches inside the container; the API key is present in the
environment; limits and shm are what the compose file says.

### Verification
```bash
docker compose up -d --build
docker compose ps
docker inspect airfare-monitor --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.ShmSize}}'
docker exec airfare-monitor python -c "from playwright.async_api import async_playwright; print('ok')"
docker exec airfare-monitor python -c "import os; assert os.environ['<LLM_API_KEY_VAR>']; print('key ok')"
docker stats airfare-monitor --no-stream
docker exec airfare-monitor python -m pytest tests/ -v -k "not slow"
```
Paste full output into `.agent/reports/017-phase-5.md`.

---

## Phase 6 — Live verification against a real opted-in tracker

### Intent
Confirm the whole pipeline works end-to-end against the real GRU→ZRH
2026-08-21 route that motivated this plan, and that failure paths are
observably graceful rather than theoretically graceful. Out of scope: any
further code changes — if this phase finds a bug, that's a small follow-up,
not silent scope creep into this phase.

### Tasks
6.1 Enable `kayak_enabled` on a real tracker for GRU→ZRH 2026-08-21 (or the
    closest still-valid date) via the Phase 3 toggle.
6.2 Manually trigger `search_and_store` once in the running container
    (with the pre-render delay skipped). Confirm: a `search_done` log entry,
    a new snapshot, and — if Kayak succeeded — that **both** Google-sourced
    and Kayak-sourced rows are in that *same* snapshot, with the TP84-style
    itinerary (or whatever is currently cheapest on Kayak) showing `Kayak`
    in the new Source column.
6.3 Confirm `best_price`/`best_source` reflect whichever source is actually
    cheapest that run — not always Kayak, not always fli. Confirm the
    dashboard trend chip did **not** move purely because Kayak joined.
6.4 If the run fails (bot detection) — expected at ~40-70% reliability —
    confirm: the snapshot was still created with fli's rows, the displayed
    price is undisturbed, a `WARNING`-level `kayak_search_error` appears on
    `/monitor`, and `kayak_next_due_at` advanced (no hot retry on the next
    tick).
6.5 Collect a **success-rate sample**: leave it running and gather ~10
    Kayak attempts, recording success/blocked/error for each, and whether
    `_looks_blocked`'s markers actually matched what PerimeterX served (vs.
    a silent zero-result page). This — not confirming jitter, which the unit
    tests already cover — is the observation the reliability follow-up plan
    needs. Note also whether attempt timestamps are visibly irregular.
6.6 Spot-check that a Kayak-quoted price appearing in the results table can
    be found by hand on kayak.com — the end-to-end guard against a
    hallucinated extraction that slipped past 2.7's grounding check.

### Files
None — verification only.

### What NOT to touch
Everything — this phase makes no code changes.

### Design decisions / open questions / risks
- Don't over-index on a ~10-attempt sample; the real tuning is the deferred
  follow-up plan.

### Tests
None new — this phase validates the accumulated suite against live behavior.

### Success criteria
6.1-6.6 all observed and written up, whether the individual Kayak runs
succeeded or failed. **A failure that degrades gracefully (6.4) is a pass** —
Kayak succeeding isn't the bar, per Decision 8.

### Verification
```bash
# Inside the running container:
python -c "import asyncio; from backend.scheduler import search_and_store; asyncio.run(search_and_store(<tracker_id>, delay=False))"
# Then check /monitor and /trackers/<tracker_id> in a browser.
pytest tests/ -v -k "not slow"   # final full non-regression pass
```
Paste observations — not just command output; this phase is about what was
actually seen — into `.agent/reports/017-phase-6.md`.

---

## Test files to revise before implementation

All test files are written and in place as of 2026-08-04:

- `tests/test_fingerprint.py` — revised in place (v1)
- `tests/test_pages_multi_source.py` — v1 tests plus three chart-input dedup
  tests (`window.allFlights` one-entry-per-key, cheapest-price-per-key,
  distinct-flight colour ranking)
- `tests/test_chart_data.py` — one added test for `get_sticky_top_flight_keys`
  returning `top_n` *distinct* flights when a key repeats in a snapshot
- `tests/test_kayak_source.py` — v1 tests plus four `_validate` grounding
  tests, one end-to-end hallucinated-price test, and one key-scrubbing test.
  **The v1 `_render` mocks returned the stub string `"<rendered page text>"`,
  which the grounding check would correctly reject** — they now return
  `_sample_body()`, text that actually contains the sample price.
- `tests/test_best_source.py` — v1 tests plus the tie-determinism test
- `tests/test_kayak_scheduling.py` — **rewritten** for the fold-in design.
  The 5 surviving v1 tests (two `kayak_enabled` column, three jitter) are
  kept verbatim; the 10 targeting `kayak_search_and_store` / `add_kayak_job`
  / `remove_kayak_job` are replaced by 14 tests exercising `search_and_store`
  directly. The file header documents what was dropped and why.

Baseline confirmed by running the suite in-container on 2026-08-04:
`61 failed, 222 passed, 3 deselected`, with every failure confined to this
plan's own test files (`test_fingerprint` 7, `test_kayak_source` 23,
`test_kayak_scheduling` 19, `test_best_source` 6, `test_pages_multi_source` 5,
`test_chart_data` 1) and no pre-existing test broken. Spot-checked failure
reasons: `sqlite3.OperationalError: no such column: kayak_enabled` (10),
`ImportError: cannot import name '_kayak_due' / '_jittered_kayak_interval_minutes'`
(6), `KeyError: 'best_source'` (4), `AttributeError: module 'backend.sources'
has no attribute 'kayak'`, and real assertion diffs for the template and
sticky-key tests — no collection errors, no typos.

## Handoff notes

- Start from `backend/sources/base.py` (the protocol every source
  implements) and `backend/sources/fast_flights.py` (the most recent
  precedent for adding a source, with its own plan at
  `.agent/plans/016-fast-flights-fallback.md`).
- `backend/scheduler.py` and `backend/db.py` are touched by every phase
  after Phase 2 — read both in full before starting Phase 3.
- **Two operations need explicit user confirmation before running:** the
  `flight_key` backfill (1.9) and the `trackers` `ALTER TABLE` (3.1). Back
  up `data/airfare.db` first; it is 183MB and there is 19G free.
- The hand prototype script (scratch, not committed) confirmed
  `kayak.com/flights/{ORIGIN}-{DEST}/{DATE}?sort=price_a` renders without
  blocking on a single request, and that `"Select"` button text is a
  reliable per-result marker in the rendered body text — reproduce that
  finding rather than trusting this note blindly; Kayak's markup shifts.
- Line numbers in this plan were taken against a tree with uncommitted
  changes to `db.py` and `pages.py`. Re-grep before editing.
- Per this project's CLAUDE.md: run each phase's verification command and
  paste full output into `.agent/reports/017-phase-N.md` before considering
  that phase done.
