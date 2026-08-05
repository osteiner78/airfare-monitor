# Plan 019 — Make Kayak's data trustworthy enough to promote

## Context

Plan 018 answered its question decisively: **0 blocks / 10**, nine genuine
results pages, four complete extractions. The evasion bundle works and needs
no further tuning. Plan 018's Step 5 (promotion) is blocked, and this plan
unblocks it.

The three defects it hit were invisible until now for one reason: plan 017
Phase 6 rendered **0 of 5** pages, so the extraction path had never once run
against real Kayak data. Nothing downstream of `_render` had ever been
exercised in production. 018 succeeded and made a whole layer observable for
the first time.

**Evidence base** — 9 captured bodies in `data/kayak-samples/`, and
`.agent/reports/018-phase-3.md`. Everything below was read off those, not
inferred. A Kayak collapsed result row looks exactly like this:

```
12:30 am – 5:40 pm
Royal Air Maroc
1 stop
CMN
 2h 55m layover, Casablanca Mohamed V
13h 10m
GRU
-
LIS
1
0
$554
Economy Cabin
Select
```

Available per row: both times, airline name, stop count, layover airport and
duration, total duration, origin/dest, price, cabin. **No flight number, on
any row, in any of the 9 bodies.**

---

## Decisions

1. **Currency: force, verify, refuse.** Plan 017 Decision 7 ("force via URL
   params, no conversion math needed downstream") is **falsified** — all 9
   bodies show `English / $ / United States dollar` despite `?currency=EUR`.
   Forcing alone cannot be trusted, and *verifying without forcing* is worse
   than useless: Kayak rows in USD alongside Google rows in EUR would make
   `best_price = MIN(price)` a comparison across currencies, which is a more
   dangerous kind of wrong than a mislabelled row. So: attempt to force,
   **read back what was actually served**, and **refuse the result** (empty
   list, `WARNING`) when they disagree. Never store a price whose currency
   we cannot vouch for. Same shape as the grounding check and the block
   check — this codebase already prefers a visible refusal to a silent
   guess.
2. **Flight identity: `airline | departure_time | arrival_time`.**
   See "The identity problem" below for why, and for the cost. **This
   requires user sign-off before Phase 2 starts** — it is the third
   `flight_key` format change and carries a 165,574-row backfill.
3. **Latency tail: accept and observe, do not raise the cap.** One of six
   thinking-disabled runs hit 32s against `_LLM_TIMEOUT_S = 30`; the other
   five were 3.5-4.7s. That profile says proxy queueing, not a budget that
   is too small — raising the cap would mostly lengthen the bad case. It
   already degrades gracefully. Revisit only if the confirmation run
   (Phase 3) shows it is not rare.
4. **Scope discipline.** This plan makes Kayak's data trustworthy. It does
   **not** improve extraction coverage, add per-result expansion, or touch
   the evasion bundle, which is settled.

### The identity problem

`make_flight_key` is `airline|flight_number|departure_time`. Kayak supplies
no flight number, so the model invented `""`, `"N/A"`, `"unknown"`, `"AT"`
for the same physical flight across runs — four keys for one flight,
fragmenting its history into disconnected series and breaking sticky top-N
and the delta diff.

The deeper consequence, which matters more: **plan 017 Phase 1's cross-source
merge cannot work for Kayak.** Phase 1 dropped `source` from `flight_key`
specifically so one physical flight quoted by Google *and* Kayak would
collapse to one identity. But `TAP AIR PORTUGAL|TP 84|…` (Google) can never
equal `TAP AIR PORTUGAL||…` (Kayak) when Kayak prints no number. The phantom
new/missing duplication Phase 1 was built to prevent returns by another
route. Phase 1 was not wrong — dropping `source` is still correct — it was
simply built before anyone had seen a Kayak row.

Options considered:

| | Identity | Cross-source merge | Cost |
|---|---|---|---|
| A | keep current, normalise Kayak's empty number | no | none |
| B | `airline\|departure_time` | yes | backfill; collides on same-airline same-minute different routings |
| C | **`airline\|departure_time\|arrival_time`** | **yes** | **backfill** |
| D | add `duration_min` instead of arrival | yes | backfill; duration is rounding-prone across sources |

**C is recommended.** All three fields are present and stable from every
source (verified: of 165,574 existing rows, 0 lack `airline` or
`arrival_time`, 29 lack `departure_time`). Arrival time disambiguates two
itineraries that share a first leg but route differently — the collision
case that sinks B — and unlike duration it is a stated clock time rather
than a computed interval, so it does not drift on rounding. It also matches
CLAUDE.md's existing observation that "uniqueness comes from
`departure_time`, not the airline segment".

**The honest cost of C:** a third `flight_key` format change, and a third
backfill of the production DB. Unlike the plan 017 migration this one is
*recomputable from existing columns* (`airline`, `departure_time`,
`arrival_time` are all stored), so it is a single UPDATE rather than string
surgery — but it is still irreversible in place and needs a backup.

**Consequence to accept either way:** Kayak-exclusive flights — the cheaper
ones this whole feature exists to surface — will still churn "new"/"missing"
whenever a Kayak run fails, because no other source quotes them. Merging
fixes churn only for flights both sources see. Distinguishing "this flight
left the market" from "the source that saw it didn't run" needs snapshot-level
per-source success recording, which is **out of scope here** and noted as
follow-up work.

---

## Phase 1 — Trustworthy currency + close the harness gap

### Intent
Stop Kayak from producing prices we cannot vouch for, and stop the sample
harness from losing exactly the attempts that matter most. Both are
prerequisites for any further live run, so they come first and together.

### Tasks
1.1 `_page_currency(body_text) -> str | None` (pure): read the currency the
    page actually served. The captured bodies carry it as an adjacent
    `$` / `United States dollar` pair in the header chrome. Return an ISO
    code where recognisable, else `None`. Build the mapping from the
    captured samples, not from guesses.
1.2 `search()`: after `_render` and the block checks, compare
    `_page_currency(body)` against the requested currency. On mismatch, set
    `last_error` naming both, `last_error_level = "WARNING"`, and return
    `[]` **without** calling `_extract` — no LLM spend on a page we are
    going to refuse anyway, same ordering rule as the block check.
    On `None` (unreadable), refuse as well: an unverifiable currency is not
    a usable one.
1.3 Investigate the real forcing mechanism and apply it in `_build_url`
    and/or the persistent context. Plan 017 task 2.3 raised this
    ("confirm the real currency param name during implementation") and never
    closed it. Note the bundle now has a **persistent profile**, so a
    currency cookie set once would carry across renders — check that path
    before assuming a URL parameter exists. Whatever is found, 1.2 stays:
    forcing is the attempt, verification is the guarantee.
1.4 Close the harness gap from 018 attempt 7: `_search_inner` awaits
    `_render` before building the sample record, so a render that hangs to
    `_OVERALL_TIMEOUT_S` records nothing at all. Build the record first and
    write a sidecar even when there is no body (`body_len: 0`,
    `outcome: "render_timeout"`), so sidecar-driven analysis stops silently
    omitting the hardest failures.

### Files
- Modify: `backend/sources/kayak.py`, `backend/kayak_samples.py` (if the
  no-body path needs it)

### What NOT to touch
- The evasion bundle: `_launch_args`, `_context_options`, `KayakRenderConfig`
  defaults, the warm-up, `_simulate_interaction`. 018 settled these at
  0 blocks / 10 and this plan has no business perturbing them.
- `_results_section` / `_extract` trimming and thinking-disabled settings.

### Tests
`tests/test_kayak_currency.py` (new — written with this plan):
- `test_page_currency_reads_usd_from_a_real_captured_body`
- `test_page_currency_returns_none_when_no_currency_marker_present`
- `test_search_refuses_result_when_page_currency_differs_from_requested`
- `test_search_does_not_call_extract_when_currency_mismatches`
- `test_search_refuses_result_when_page_currency_is_unreadable`
- `test_search_proceeds_when_page_currency_matches_requested`

`tests/test_kayak_samples.py` (added):
- `test_sample_is_recorded_even_when_render_produced_no_body`

### Success criteria
All of the above pass; full suite green.

### Verification
```bash
pytest tests/test_kayak_currency.py tests/test_kayak_samples.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/019-phase-1.md`.

---

## Phase 2 — Flight identity (**needs sign-off on Decision 2 first**)

### Intent
Give one physical flight one identity, across sources and across runs.

### Tasks
2.1 `make_flight_key` → `f"{airline}|{departure_time}|{arrival_time}"`.
2.2 Normalise the airline segment — casefold and collapse whitespace — so
    `"TAP AIR PORTUGAL"` and `"TAP Air Portugal"` do not fork one flight in
    two. Verify against the real airline strings both sources emit before
    choosing the normalisation.
2.3 `KayakSource`: stop emitting invented flight numbers. The extraction
    prompt must say the list view has none and require `null`; `_map_result`
    normalises `"N/A"`/`"unknown"`/`null` to `""`. `flight_number` stays a
    *display* field, absent for Kayak rows — it is simply no longer part of
    identity.
2.4 **Production backfill — explicit user confirmation, backup first.**
    Recomputable from stored columns, unlike the plan 017 migration.

    **Corrected 2026-08-05.** This task originally read
    `SET flight_key = airline || '|' || …`, concatenating the **raw** airline.
    That contradicts task 2.2: `make_flight_key` normalises the airline
    segment, so every backfilled row would have disagreed with the keys the
    running code generates — for every airline not already lowercase, i.e.
    nearly all of them. The backfill would have detached history rather than
    preserving it, which is the one thing it exists to do.

    **Prefer a one-shot Python backfill that calls `make_flight_key` itself**
    over hand-written SQL. Equivalence by construction beats equivalence by
    coincidence: SQLite's `LOWER()` is ASCII-only without ICU while Python's
    `.lower()` is Unicode-aware, and `TRIM()` strips only leading/trailing
    whitespace while a Python `" ".join(s.split())` also collapses internal
    runs. 165k rows is trivial to stream in Python.

    If SQL is used anyway, it must mirror 2.2 exactly
    (`LOWER(TRIM(airline)) || '|' || …`), and the three preconditions that
    make that equivalent must be **re-checked, not assumed** — verified on
    2026-08-05 as 40 distinct airlines with 0 non-ASCII, 0 internal
    double-spaces, 0 leading/trailing whitespace. Record those preconditions
    next to the SQL in `CLAUDE.md`: this project restores from old backups
    (see the plan 017 migration note), and a restored DB containing a
    non-ASCII airline would silently diverge.

    ```bash
    docker compose stop
    cp data/airfare.db data/airfare.db.bak-019
    # ... backfill (Python one-shot preferred, see above) ...
    docker compose start
    ```
    165,574 rows; 29 have an empty `departure_time` and will land on a
    2-separator key — harmless, but confirm the count is still 29 first.
2.5 Re-verify the five dedup sites from plan 017 Phase 1 plus `history_by_key`
    still behave, since the merge rate changes: rows that were distinct may
    now collapse.
2.6 **Multi-carrier airline names — take the first carrier** (added
    2026-08-05, flagged during 2.1-2.5 as needing a decision). Kayak names a
    connecting itinerary by every operator (`"Azul, easyJet"`); the Google
    sources name only the first (`fast_flights.py:120`,
    `airline = r.airlines[0]`). Casefolding cannot bridge that, so such
    flights would never merge across sources — the exact duplication this
    phase exists to remove.
    Decision: `KayakSource` emits the **first** carrier only, matching the
    existing convention. No backfill needed — verified 2026-08-05 that all
    40 distinct airline values already stored are single-carrier, so Google
    rows are already in this form. A wrong merge would require the same
    first carrier *and* the same departure *and* arrival time, which is the
    same physical itinerary.
    Test: `test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary`.

### Files
- Modify: `backend/fingerprint.py`, `backend/sources/kayak.py`
- Operational: live `data/airfare.db` (2.4, gated)

### Tests
`tests/test_fingerprint.py` (revised in place — same convention as 017):
- `test_flight_key_has_three_parts_of_airline_and_both_times`
- `test_flight_key_excludes_flight_number`
- `test_flight_key_matches_across_sources_when_one_lacks_a_flight_number`
  (**the point of this phase**)
- `test_flight_key_normalises_airline_casing_and_whitespace`
- `test_flight_key_differs_for_same_airline_and_departure_but_different_arrival`
  (the routing-collision case that ruled out option B)
- existing non-regression tests updated to the new arity

`tests/test_kayak_source.py` (added):
- `test_map_result_normalises_placeholder_flight_numbers_to_empty`
- `test_extraction_prompt_states_the_list_view_has_no_flight_numbers`

### Success criteria
All of the above pass; full suite green; after 2.4, a detail page still
shows chart lines spanning full history.

### Verification
```bash
pytest tests/test_fingerprint.py tests/test_kayak_source.py -v
pytest tests/ -v -k "not slow"
sqlite3 data/airfare.db "SELECT flight_key FROM flight_prices LIMIT 3;"
```
Paste into `.agent/reports/019-phase-2.md`.

---

## Phase 3 — Live confirmation run

### Intent
Measure, rather than infer, that the pipeline now produces trustworthy rows
end to end. Plan 018's 3.2/3.3 extraction fixes were validated against
*captured* bodies only — "4/9 → ~9/9" is a reasonable inference and an
unmeasured one.

### Tasks
3.1 3-5 attempts, ~10 min apart, on the **same throwaway route** as 018
    (`GRU→LIS`, `2026-10-04`) so the comparison is like-for-like. Residential
    IP. Tracker 20 stays `kayak_enabled=0` throughout.
3.2 Record per attempt: blocked, currency verified, extracted rows,
    validated rows, and — new — the resulting `flight_key`s, to confirm the
    same physical flight yields the same key across attempts.
3.3 Compare against 018's baseline: 9/10 rendered, 4/9 extracted.

### Success criteria
Block rate still ~0. Extraction success materially above 4/9. Every stored
row's currency verified. The same flight produces a stable key across
attempts.

### Verification
Results table in `.agent/reports/019-phase-3.md`, one row per attempt.

---

## Phase 4 — Promote

Only after Phase 3. Re-enable Kayak on tracker 20, then close plan 017's
Phase 6: tasks 6.3 (best_source reflects the genuinely cheapest source),
6.4 (Kayak failing while the main sources succeed leaves the displayed price
undisturbed — now observable, since the `fast_flights` TypeError that
confounded it was fixed 2026-08-05), and 6.6 (hand spot-check a Kayak-quoted
price against kayak.com).

---

## Follow-up, explicitly out of scope

- **Per-source success recording per snapshot.** Kayak-exclusive flights will
  churn "new"/"missing" whenever a Kayak run fails, regardless of identity
  scheme. Distinguishing "left the market" from "not checked this cycle"
  needs the snapshot to record which sources ran successfully. Real, but a
  separate concern from data correctness.
- **Extraction coverage.** 018 measured 4/9; the fixes should raise it, but
  raising it *further* (per-result expansion, a stronger model) is its own
  question.
- **The driver crash.** `Connection closed while reading from the driver`
  fired twice on 2026-08-04/05, each leaving a ~190MB core dump. It did not
  recur across 018's 10 attempts. Watch it; do not chase it yet.
