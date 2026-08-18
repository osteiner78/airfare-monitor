# 028 — SearchQuery, tracker_sources, Passengers, and database compression

**Date:** 2026-08-18
**Supersedes the roadmap entries:** "Passengers (adults + children with ages)",
"Database size: normalise first, then compress the series", and the
`tracker_sources` prerequisite recorded under "Additional sources".

**Decisions taken before planning (user-confirmed):**

| Decision | Choice |
|---|---|
| Target | The **next** trip — all 7 current trackers depart Aug 20–22 and cannot benefit |
| Price semantics | Store **TOTAL** for the party + `passenger_count`; UI derives per-person |
| Party changes | **Frozen** after tracker creation; to change party, create a new tracker |
| `tracker_sources` scope | Opt-in **browser sources only** (kayak, later skyscanner); Google stays always-on |
| Infants | **Included** — modelled now, for eventual public use |
| `booking_url` | **Interned** into a side table, not dropped |
| Source boundary | **Option C** — a `SearchQuery` dataclass replaces the 6 positional args |
| Verification | Cross-source agreement, page-grounded party, URL construction, storage invariants |
| Out of scope | Skyscanner implementation, fare brand/baggage, expandable-row UI |

---

## Findings from the codebase analysis that shape this plan

**1. Both Google-side libraries take counts, not ages.** Verified against the
installed packages:

```
fli:           PassengerInfo(adults, children, infants_in_seat, infants_on_lap)
fast_flights:  Passengers(adults, children, infants_in_seat, infants_on_lap)
```

Identical field names, so one internal model maps 1:1 to both. But Kayak's URL
takes **ages** while Google takes **buckets**. The party model must therefore
carry ages *and* derive counts, and `infants_in_seat` vs `infants_on_lap` is a
**choice that no age can imply** — so the roadmap's `child_ages = [6]` shape is
insufficient. Ages are discarded for Google; that is expected, not a bug.

**2. `fast_flights` passes no `passengers` argument at all today**
(`fast_flights.py:59-63`), so its 1-adult behaviour is an implicit library
default. Note `Passengers.__init__` defaults `adults=0` — constructing
`Passengers()` naively would request **zero** adults. Never build it empty.

**3. Cross-source agreement is only tight for adults-only parties.** Google
buckets a 6- and an 11-year-old identically; Kayak may not. The check keeps a
tight tolerance for adults-only trackers (measured 0.7% today: €818 vs €824 on
one `flight_key`) and loosens when children are present. It retains full power
against the ×N conversion bug, which is party-size-driven, not age-driven.

**4. Kayak's `/2adults/children-6` URL form is asserted by the roadmap and
tested by nothing.** `?currency=EUR` was sent for weeks and silently ignored;
the same assumption must not be made twice. Phase 4 verifies it against a real
render before anything depends on it.

**5. There will be no live traffic after Aug 22.** Every tracker pauses when its
`depart_date` passes. Live verification requires deliberately creating a tracker
with a distant departure date — task 4.9, not a mid-implementation surprise.

---

## Phase 1 — `SearchQuery` replaces the positional argument list

### Intent

A pure refactor, shipped and verified before any feature rides on it. The one
design decision: `search()` takes a single frozen `SearchQuery` rather than
growing a seventh positional argument, because fare brand, baggage and cabin
class are all queued behind Passengers and each would otherwise repeat this
same 13-file sweep. No party field is added here and no behaviour changes —
this phase exists so that Phase 4's diff is about passengers, not about
plumbing. Explicitly out of scope: any passenger concept, any schema change.

### Tasks

- **1.1** Add `@dataclass(frozen=True) SearchQuery` to `backend/sources/base.py`
  with `origin`, `dest`, `depart_date`, `return_date`, `currency`, `top_n`.
- **1.2** Change the `SearchSource` protocol's `search()` to
  `async def search(self, query: SearchQuery) -> list[FlightResult]`.
- **1.3** Update `GoogleFlightsSource.search`/`_fetch` to take the query object.
- **1.4** Update `FastFlightsSource.search`/`_fetch` likewise.
- **1.5** Update `KayakSource.search`/`_search_inner` likewise.
- **1.6** Update `FallbackSource.search` — it forwards to both arms
  (`fallback.py:26,33`).
- **1.7** Update the 2 scheduler call sites (`scheduler.py:107,134`) and
  `scripts/kayak_experiment.py:70`.
- **1.8** Mechanically update the 13 test files that call `.search(...)`
  positionally. **Adapt call sites only — do not change any assertion.**

### Files

`backend/sources/base.py`, `google_flights.py`, `fast_flights.py`, `kayak.py`,
`fallback.py`, `backend/scheduler.py`, `scripts/kayak_experiment.py`, and the
13 test files listed by
`grep -rln "\.search(" tests`.

### Risks

`scripts/kayak_experiment.py` and `scripts/kayak_model_benchmark.py` are not
covered by tests — grep them explicitly rather than trusting the suite.

## What NOT to touch

`fingerprint.py`, `_strip_blocks` and its wrappers, the timeout constants
(pinned by a source-reading test), `FlightResult`'s fields, `db.py`.

### Success criteria

`test_search_query_carries_every_field_the_old_signature_had`,
`test_search_query_is_frozen`,
`test_every_source_satisfies_the_search_source_protocol`,
plus the whole existing suite unchanged.

### Verification

```bash
docker exec airfare-monitor pytest tests/ -q -k "not slow"
grep -rn "\.search(" backend scripts | grep -v "def search" | grep -v "_RE\.search"
```

---

## Phase 2 — `tracker_sources` replaces the per-source column pair

### Intent

`trackers.kayak_enabled` + `kayak_next_due_at` is one column pair per source,
and Phase 3 is about to add party columns to that same table while Skyscanner
would add a second pair. The decision is to model **only opt-in browser
sources** as rows: `FallbackSource` is a composite whose secondary runs only
when the primary is empty (`fallback.py:26-33`), so `google_flights` and
`fast_flights` are not independently schedulable and modelling them as peers
would either lie about that relationship or force primary/secondary into the
schema for no present benefit. Out of scope: changing how Google is scheduled.

### Tasks

- **2.1** Add `tracker_sources(tracker_id, source, enabled, next_due_at)` to
  `_SCHEMA`, PK `(tracker_id, source)`, FK cascade on `tracker_id`.
- **2.2** Write `scripts/migrate_028_tracker_sources.py` copying every
  `kayak_enabled`/`kayak_next_due_at` value into a `('kayak', …)` row.
  Idempotent; takes the DB path as argv.
- **2.3** Add `get_tracker_sources(tracker_id)` and
  `set_tracker_source(tracker_id, source, enabled=None, next_due_at=None)`
  to `db.py`.
- **2.4** Rewrite `search_and_store`'s Kayak block to iterate enabled browser
  sources instead of reading the two columns.
- **2.5** Read every row with `.get(...)`, never `[...]` — the Active-dev rule
  from CLAUDE.md; a missing table or row must degrade to "feature off".
- **2.6** Point `PATCH /trackers/{id}/toggle-kayak` at `set_tracker_source`,
  keeping the route and its returned partial unchanged.
- **2.7** Rename `_get_kayak_render_lock` to `_get_browser_render_lock` and keep
  it **one process-wide lock** — container limits (`1.5G`/`2.0` cpus,
  `shm_size: 1gb`) were measured for exactly one Chromium.
- **2.8** Leave `trackers.kayak_enabled`/`kayak_next_due_at` **in place and
  unread** for one release. Dropping columns is destructive and reversible only
  from backup; a follow-up removes them once the new path has run a full day.

### Files

`backend/db.py`, `backend/scheduler.py`, `backend/pages.py`,
`scripts/migrate_028_tracker_sources.py`.

### Risks

Production runs Active dev, so new code meets the old table between the edit and
the migration. 2.5 is what makes that window safe. **The migration is
confirmation-gated** — do not run it against `data/airfare.db` without asking.

## What NOT to touch

`get_sources()` and `FallbackSource` — Google's scheduling is unchanged.
`kayak.py` itself: this phase is scheduling, not rendering.

### Success criteria

`test_a_tracker_with_no_source_rows_runs_google_only`,
`test_enabling_kayak_creates_exactly_one_source_row`,
`test_a_missing_tracker_sources_table_degrades_to_feature_off`,
`test_next_due_at_advances_after_a_failed_browser_source_run`,
`test_toggle_kayak_route_still_returns_its_partial`.

### Verification

```bash
docker exec airfare-monitor pytest tests/test_tracker_sources.py tests/test_kayak_scheduling.py tests/test_kayak_cadence.py -q
docker exec airfare-monitor pytest tests/ -q -k "not slow"
python3 scripts/migrate_028_tracker_sources.py /tmp/copy-of-prod.db && sqlite3 /tmp/copy-of-prod.db "SELECT * FROM tracker_sources;"
```

---

## Phase 3 — the party model and its schema

### Intent

Introduce the party as data, with no source wired to it yet, so the migration
and the freeze rule can be verified in isolation. The central decision is that
`Party` carries **ages** (Kayak needs them) and **derives counts** (Google needs
those), with `infants_on_lap` as an explicit flag no age can imply. Prices are
stored as the party TOTAL alongside `passenger_count`, so an existing 1-adult
row remains correct without rewriting a single byte. Out of scope: passing the
party to any source — that is Phase 4.

### Tasks

- **3.1** Add `@dataclass(frozen=True) Party` to `backend/party.py` (leaf
  module, no project imports): `adults: int`, `child_ages: tuple[int, ...]`,
  `infants_on_lap: int`.
- **3.2** Add derived properties: `children` (ages 2–11), `infants_in_seat`
  (ages < 2 minus `infants_on_lap`), `total_travellers`. Ages ≥ 12 count as
  adults, matching Google's buckets.
- **3.3** Add `Party.validate()` rejecting: zero total travellers, negative
  counts, `infants_on_lap` exceeding the number of under-2 ages, and
  `infants_on_lap` exceeding `adults` (a lap infant needs a lap).
- **3.4** Add `trackers.adults` (default 1), `trackers.child_ages` (TEXT, JSON
  array, default `'[]'`), `trackers.infants_on_lap` (default 0).
- **3.5** Add `flight_prices.passenger_count` (INTEGER, default 1) — existing
  rows are 1-adult totals and stay valid by construction.
- **3.6** Write `scripts/migrate_028_party_columns.py` (`ADD COLUMN` only,
  metadata-only, safe against a running container).
- **3.7** Enforce the freeze: `update_tracker` rejects any party field when the
  tracker already has snapshots. Raise a specific error the routes can render.
- **3.8** Add `Party` to `TrackerCreate` in `models.py` and to the add-tracker
  form; default is one adult so existing behaviour is unchanged.

### Files

`backend/party.py` (new), `backend/db.py`, `backend/models.py`,
`backend/pages.py`, `frontend/templates/partials/add_form.html`,
`scripts/migrate_028_party_columns.py`.

### Risks

`historical_best_price` is `MIN` over all rows and never recomputed. The freeze
is what keeps it meaningful; if 3.7 is weakened, that column silently starts
comparing unlike quantities forever.

## What NOT to touch

Any source file. `make_flight_key` — party is **not** part of flight identity;
the same physical flight priced for 1 or 4 travellers is still one flight.

### Success criteria

`test_party_of_one_adult_is_the_default`,
`test_child_aged_eleven_counts_as_a_child_and_twelve_counts_as_an_adult`,
`test_infant_on_lap_is_not_also_counted_in_seat`,
`test_party_with_no_travellers_is_rejected`,
`test_more_lap_infants_than_adults_is_rejected`,
`test_changing_party_on_a_tracker_with_history_is_rejected`,
`test_existing_rows_read_as_one_passenger`.

### Verification

```bash
docker exec airfare-monitor pytest tests/test_party.py tests/test_db.py -q
docker exec airfare-monitor pytest tests/ -q -k "not slow"
```

---

## Phase 4 — the party reaches both sources, and the page confirms it

### Intent

Wire the party end to end and prove the sites actually honoured it. The decision
that matters: **verify, do not trust** — the party is read back off Kayak's
rendered page the same way `_page_currency` reads the currency back, because
this project already shipped a `?currency=EUR` parameter that was silently
ignored for weeks. Kayak prices per person, so its rows are multiplied by
`total_travellers` at extraction, and that multiplication is the single most
dangerous line in this plan. Out of scope: fare brand, baggage, cabin class.

### Tasks

- **4.1** Add `party: Party` to `SearchQuery`, defaulting to one adult so
  Phase 1's callers keep working.
- **4.2** `google_flights.py:80` — build `PassengerInfo` from the party instead
  of the `adults=1` literal.
- **4.3** `fast_flights.py:59-63` — pass `passengers=Passengers(...)` built from
  the party. **Never construct `Passengers()` empty** (it defaults `adults=0`).
- **4.4** `kayak.py::_build_url` — add the party path segment. **Verify the real
  form against a live render first (4.8); do not build on the roadmap's
  assumption.**
- **4.5** Multiply Kayak's extracted per-person price by `total_travellers`
  before `_map_result`, and state the reasoning in a comment at that line.
- **4.6** Add `_party_grounded(body_text, party)` to `kayak.py`, mirroring
  `_page_currency`: on mismatch, set `last_error_level = "WARNING"` and return
  `[]` rather than storing a party the site did not apply.
- **4.7** Store `passenger_count` on every row via the scheduler's
  `{**asdict(r), …}` dict.
- **4.8** **Verify Kayak's party URL form against a real render** and paste the
  observed segment into the phase report.
- **4.9** Create a verification tracker with a departure date ≥ 60 days out —
  there is no other live traffic after Aug 22.
- **4.10** Show total + per-person + party size in the UI
  (e.g. "€1,258 · €629 pp · 2 travellers").

### Files

`backend/sources/base.py`, `google_flights.py`, `fast_flights.py`, `kayak.py`,
`backend/scheduler.py`, `frontend/templates/partials/detail_page.html`,
`tracker_card.html`.

### Risks

The ×N multiplication is the feature's highest-consequence line: forget it and
Kayak reads ~N× cheaper than Google and wins every headline; double it and it
never wins. Both are caught by the cross-source check, which is why that test is
mandatory rather than optional.

## What NOT to touch

`_validate`'s grounding checks — the party check is an **addition**, never a
carve-out. `_strip_blocks` and its wrappers. `fingerprint.py`.

### Success criteria

`test_google_passenger_info_is_built_from_the_party`,
`test_fast_flights_never_requests_zero_adults`,
`test_kayak_url_contains_the_party_segment`,
`test_kayak_per_person_price_is_multiplied_by_party_size`,
`test_a_page_that_did_not_apply_the_party_returns_no_rows_at_warning`,
`test_every_stored_row_carries_its_trackers_passenger_count`,
`test_two_sources_quoting_one_flight_agree_within_tolerance_for_adults_only`.

### Verification

```bash
docker exec airfare-monitor pytest tests/test_party_sources.py tests/test_kayak_source.py -q
docker exec airfare-monitor pytest tests/ -q -k "not slow"
curl -s -X POST http://localhost:8100/api/trackers/<verification-tracker>/search
sqlite3 -readonly data/airfare.db "SELECT source, price, passenger_count FROM flight_prices WHERE snapshot_id=(SELECT MAX(id) FROM snapshots) ORDER BY price;"
```

---

## Phase 5 — intern `legs_json` and `booking_url` (lossless)

### Intent

Reclaim 121 MB of the 182 MB `flight_prices` table with no decision about what
history is worth keeping. Measured: `legs_json` holds 275,980 rows of **2,993**
distinct values, and `COUNT(DISTINCT flight_key||legs_json)` is *also* 2,993 —
the legs are a pure function of the flight, so a side table keyed on the value
is exactly correct. `booking_url` is 276,493 rows of **30** distinct strings.
Nothing reads either column today, so the added join costs nothing on any
current read path. Out of scope: the price series — that is Phase 6.

### Tasks

- **5.1** Add `flight_legs(id, legs_json)` and `booking_urls(id, url)`, each
  with a UNIQUE index on the value.
- **5.2** Add nullable `legs_id`/`booking_url_id` to `flight_prices`.
- **5.3** `insert_flight_prices` interns on write (get-or-create).
- **5.4** Write `scripts/migrate_028_intern_text.py`: populate side tables,
  backfill the FKs, verify every row round-trips, then `VACUUM`.
- **5.5** Re-check the two preconditions before migrating — distinct-value
  counts may have moved since 2026-08-15.
- **5.6** Keep the original columns populated for one release; a follow-up drops
  them once the round-trip check has passed on production.
- **5.7** Record before/after file size and the reclaimed total in the report.

### Files

`backend/db.py`, `scripts/migrate_028_intern_text.py`.

### Risks

The migration rewrites ~276k rows. **Back up first; confirmation-gated.**
SQLite does not shrink the file without `VACUUM`, which needs free space equal
to the database size — check `df -h` before running.

## What NOT to touch

`flight_prices.price`, `flight_key`, timestamps — this phase moves *text*, not
identity or money.

### Success criteria

`test_two_rows_with_identical_legs_share_one_legs_row`,
`test_interned_legs_round_trip_to_the_original_json`,
`test_an_empty_legs_json_is_interned_once_not_per_row`,
`test_a_unicode_booking_url_round_trips`,
`test_null_legs_json_stays_null`.

### Verification

```bash
docker exec airfare-monitor pytest tests/test_intern_text.py tests/test_db.py -q
cp data/airfare.db /tmp/pre-intern.db && python3 scripts/migrate_028_intern_text.py /tmp/pre-intern.db
sqlite3 -readonly /tmp/pre-intern.db "SELECT count(*) FROM flight_prices fp JOIN flight_legs l ON l.id=fp.legs_id WHERE l.legs_json <> fp.legs_json;"
ls -la data/airfare.db /tmp/pre-intern.db
```

---

## Phase 6 — run-length compress the price series (after Passengers settles)

### Intent

The last phase deliberately, because it compresses *price history* and a
party-size change resets or freezes histories — compressing data that Phase 3–4
may render moot is wasted work. Measured: 141,910 of 276,493 rows (**51.3%**)
are interior points of a run where a flight held the same price in both the
previous and next observation. The decision that makes this safe: runs become
**explicit** via `observed_until`, never implicit by deleting rows — because
this app reads a row's *absence* from a snapshot as "flight no longer offered",
which drives the `missing` delta and the blended reconstruction.

### Tasks

- **6.1** Re-measure the 51.3% figure — it will have moved.
- **6.2** Add `observed_until` to `flight_prices`, defaulting to the row's own
  snapshot time so existing rows keep today's meaning exactly.
- **6.3** Extend the run rather than inserting when a flight's price is
  unchanged from its own source's previous observation.
- **6.4** Teach `get_price_history` to expand a run into its endpoints so chart
  shapes are byte-identical to today's.
- **6.5** Teach the blending/`missing` logic that a row whose run covers a
  snapshot was **present**, not missing.
- **6.6** Prove `historical_best_price` is unchanged for every tracker,
  before and after (`MIN` over a flat run is preserved by its endpoints).
- **6.7** Write `scripts/migrate_028_runlength.py`, back up, `VACUUM`, record
  the reclaimed size.

### Files

`backend/db.py`, `backend/pages.py`, `scripts/migrate_028_runlength.py`.

### Risks

The highest-risk phase in this plan. It touches the blending and `missing`
machinery that plans 019/020 spent two weeks getting right, and a mistake makes
a flight look withdrawn when it merely held its price. If the `missing` tests
cannot be kept green without changing their assertions, **stop and re-plan** —
that is the signal the design is wrong, not the tests.

## What NOT to touch

`historical_best_price`'s definition. `flight_key`. The `_BLEND_GROUPS` rule.

### Success criteria

`test_a_flat_price_run_stores_endpoints_not_every_observation`,
`test_expanding_a_run_reproduces_the_original_chart_points`,
`test_a_flight_inside_a_run_is_not_reported_missing`,
`test_a_flight_that_actually_disappears_is_still_reported_missing`,
`test_historical_best_price_is_identical_before_and_after_compression`.

### Verification

```bash
docker exec airfare-monitor pytest tests/test_runlength.py tests/test_blended_sources.py tests/test_chart_data.py -q
docker exec airfare-monitor pytest tests/ -q -k "not slow"
sqlite3 -readonly data/airfare.db "SELECT tracker_id, MIN(price) FROM flight_prices GROUP BY tracker_id;"   # before and after — must match exactly
```

---

## Deliverables

**Plan:** this file.

**Test files** (written before implementation, and **run once to confirm each
fails or passes for the right reason** — actual measured state below):

| File | Phase | Fail now (NEW / FAILURE-MODE) | Pass now (NON-REGRESSION anchors) |
|---|---|---|---|
| `tests/test_search_query.py` | 1 | 5 | 5 |
| `tests/test_tracker_sources.py` | 2 | 9 | 0 |
| `tests/test_party.py` | 3 | 19 | 0 |
| `tests/test_party_sources.py` | 4 | 20 | 1 |
| `tests/test_intern_text.py` | 5 | 3 | 6 |
| `tests/test_runlength.py` | 6 | 4 | 7 |

**The pass/fail split is itself meaningful and must be preserved.** In Phases 5
and 6 most tests pass *today*: interning and run-length are **lossless**
transformations, so every round-trip, chart-shape, `missing`-semantics and
`historical_best_price` assertion is an anchor that must survive the change
untouched. Only the tests asserting the new *storage* shape (one shared
`flight_legs` row, endpoints instead of every observation) fail now. If a
Phase 5 or 6 implementation makes an anchor fail, the transformation was not
lossless — that is the signal to stop, not to adjust the test.

Failures are raised inside test bodies (function-level imports, matching the
existing suite's convention) so collection always succeeds and each test fails
individually naming what is missing, rather than taking the file down as a
collection error.

Every existing test file is a **NON-REGRESSION anchor** and must pass unchanged
throughout, with one allowed exception: Phase 1 adapts `.search(...)` *call
sites* in 13 files without touching a single assertion.

---

## Handoff notes

- **Read first:** `CLAUDE.md` (especially "Flight source architecture", "DB path
  convention", the `flight_key` note, and the Active-dev column-read rule),
  `.agent/plans/024` (why observability is `last_error`, not `logger.warning`),
  `.agent/plans/025` (why identity normalisation lives in `fingerprint.py`),
  `.agent/plans/027` (the strip-block and scheduler conventions this plan
  builds on).
- **Every migration in this plan is confirmation-gated.** Ask before running any
  of them against `data/airfare.db`, and back up first.
- **`tracker.get(...)`, never `tracker[...]`** for any column this plan adds.
- **There is no live traffic after Aug 22** — task 4.9 creates the tracker that
  makes live verification possible at all.
- A phase is complete only when its tests pass **and** the full verification
  output is pasted into `.agent/reports/028-phase-N.md`.
