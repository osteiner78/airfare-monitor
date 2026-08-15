# TODO

## Bugs
- [X] **`GET /api/trackers` returns `active` as int** — list endpoint bypasses `TrackerResponse` Pydantic model, serializes `active` as `1`/`0` instead of `true`/`false`.

## Improvements
- [ ] **Design polish** — pass through Claude Design for UI/UX improvements.
- [ ] **Bundle Chart.js locally** — currently loaded from jsdelivr CDN. Bundle for offline use.
- [x] Change currency symbol -> EUR to <euro symbol>
- [x] **Replace airline codes with airline logos/icons**


### Dashboard
- [x] **Trackers list**: Include historical best price



### Tracker details

#### Tracker details box
- [x] **Details box**: move ACTIVE badge and pause+delete buttons to the right side. Leave Google Flighs and Search Now button on the right side

#### Chart
- [x]] **Fix chart tooltip** — change times to local times, add currency to price
- [x] **Fix chart tooltip** — tooltip shows raw price without currency symbol and uses epoch timestamps. Should show formatted date + currency (e.g., "May 31 19:44 — 102.00 EUR").

#### Table
- [x] Change "Current Results" to "Last prices fetched (<time> ago)"
- [ ] Add a selection box besides all flights, when checked it adds it to the chart -> will require storing historical prices for all flights
- [x] **Remove Arrival Date**: leave only departure date. If arrival date is next day, add string "(+1 day)" beside the arrival time
- [ ] **Fetch per-flight booking URLs** — using fli's `get_booking_options()`.
- [ ] **A stale source silently vanishes from the detail page.** Noted in the
  022/023 code review (N7) and left as a UI gap, not a correctness bug —
  `/monitor` still carries the WARNING when a source ages out past
  `2 * interval_minutes` (see "Sources are BLENDED per source" in CLAUDE.md),
  but the detail page itself gives no visible signal that a source is missing
  rather than simply having no cheaper fares. Some indicator (a greyed-out
  source chip, a "Kayak last seen Xh ago" note) would make the gap visible
  without digging into `/monitor`.


## Roadmap

### Code review — do this BEFORE Passengers
- [x] **Audit the codebase for cross-file invariants that nothing pins.** Added
  2026-08-12 after a run of defects that were not independent accidents but
  one repeating shape.

  **The pattern.** Recent bugs, and what class each belongs to:
  - `_dedupe_rows` compared raw extracted fields while the normalisations that
    make rows identical (`_first_carrier`, `_canonical_timestamp`) ran later in
    `_map_result` (fixed 2026-08-12, `130b205`) — *ordering dependency between
    two functions, stated nowhere*.
  - `_OVERALL_TIMEOUT_S` assumed an in-process render bound after plan 021 gave
    the worker a `2.5x` budget, cutting slack 30s → 7.5s and losing a good page
    mid-extraction (fixed 2026-08-11) — *constant derived from a constant that
    moved*.
  - `fast_flights::_to_iso` returning `""` was safe only while `flight_key`
    carried `flight_number`; plan 019 removed it and 96 unidentifiable rows
    reached production — *a distant change invalidated a local assumption, and
    nobody re-audited the callers*.
  - `FallbackSource` served degraded results without setting `last_error`, so
    fli failing looked exactly like fli succeeding — *the observability
    contract (`last_error` is the only channel `/monitor` sees) held by
    convention, not by construction*.

  **The honest caveat:** all four were found by reading production data, not by
  reading code. A review is worth doing, but it is a complement to the data
  checks, not a replacement — budget the time accordingly and do not expect it
  to retire the two open watch items (airline grounding, the `| Ad` /
  `Sponsored` variants), which only live traffic can close.

  **Scope, in priority order** — hunt for the shape above, not for style:
  - **Ordering and derivation couplings.** Every place one function's output
    feeds another's comparison, or one constant is computed from another. The
    fix is usually a test asserting the invariant (as
    `test_dedupe_identity_agrees_with_what_actually_gets_stored` and
    `tests/test_kayak_timeout_budget.py` now do), not a code change.
  - **`flight_key`'s seven-plus dedup sites.** CLAUDE.md lists them; the audit
    question is "does this assume one row per `flight_key` per snapshot?", and
    the list was last verified before `_group_duplicate_price_rows` (`3e947f9`)
    added an eighth consumer.
  - **Silent-degradation paths.** Anywhere a source, render, or extraction can
    return fewer rows or none while reporting success. `logger.warning` never
    reaches `system_logs`; only `last_error`/`last_error_level` does.
  - **Guards that answer a narrower question than the one that matters.**
    `_validate` asks "is this printed on the page?", never "does it belong to
    this route/row?" — which is why adverts, nearby-airport promos and
    self-transfer fares each needed their own strip. Assume there is a fourth.
  - **Tracker-column reads on the main search path.** `tracker.get(...)`, never
    `tracker[...]` — a missing column must degrade to "feature off". This will
    matter immediately, since Passengers adds columns.

  **Out of scope:** refactoring for its own sake, style, and anything that
  touches `historical_best_price` semantics. Findings get recorded, not
  opportunistically fixed mid-review.

  **Why here and not later:** Passengers is the largest queued change and it
  lands on exactly these seams — both sources' URL/filter construction, the
  price semantics (`per-person` vs `total`), and new `trackers` columns read on
  the search path. Reviewing after it ships means reviewing a bigger surface
  with a live data-corruption risk attached. Fare brand + baggage is sequenced
  with Passengers, so this is the last clean seam before a multi-part change.

  **Deliverable:** `.agent/reports/022-code-review.md`, findings ranked by
  blast radius, each with the invariant it breaks and whether a test can pin
  it. Run it with `/code-review`.

  **Done 2026-08-13.** Two independent reviews (`022-code-review.md`,
  `023-code-review-cross-file-invariants.md`) plus a consolidation/remediation
  pass (`.agent/plans/024-code-review-remediation.md`, phases 0–6) fixed the
  certain one-liners, the airline-identity fork, the render worker's timeout
  premise, and display-stability findings. Two items were deliberately left
  open rather than fixed — see the standing data checks below and the two
  live-traffic watch items already on this list (airline grounding
  IATA-vs-name, `| Ad` / `Sponsored` placement variants).

  **Standing data checks** (run before trusting a Kayak-only all-time low;
  both returned zero rows as of 024's verification):
  - Rows whose departure date falls outside `[depart_date, depart_date+1]`
    (022 N4 / 023 A8) — a Kayak extraction landing on an ungrounded calendar
    date.
  - Same-carrier, same-clock-time pairs one day apart with departure hour
    `>= 3` (024's F6) — a night-rollover rebase (`_rebase_departure_date`,
    CLAUDE.md) misfiring outside its intended early-morning window.

### Passengers (adults + children with ages)
- [ ] **Track a party, not one adult.** Every tracker currently searches for a
  single adult, so a family's real cost is invisible and any manual
  cross-check against kayak.com/Google disagrees with the tool. Surfaced
  2026-08-11: a manual 2-passenger search (1 adult + 1 child aged 6) showed
  €629/person while the tool showed a 1-adult fare — the numbers were never
  comparable.

  Scope, roughly in dependency order:
  - `trackers` gains `adults` (default 1) and `children` — children need
    **ages**, not just a count: airlines price infants (<2), children (2-11)
    and youths differently, and Kayak/Google both require the age per child.
    Store as a small JSON array, e.g. `child_ages = [6]`.
  - Both sources must pass the party through. `fli` takes `PassengerInfo`
    (already constructed in `google_flights.py`, currently hardcoded).
    Kayak encodes it in the URL path segment (e.g. `/2adults/children-6`),
    so `KayakSource._build_url` changes and **every captured sample predating
    the change becomes non-comparable** — note it in the sample sidecar.
  - Decide what a "price" means once a party is involved. Kayak shows
    **per-person**, Google shows **total**. Mixing them silently would corrupt
    history far more quietly than the advert bug did. Suggested: store the
    **total** (unambiguous, sums correctly) plus `passenger_count`, and let
    the UI derive per-person. Whichever is chosen, existing rows are
    1-adult totals and stay valid.
  - Presentation: show the total as the headline with per-person underneath
    (e.g. "€1,258 · €629 pp · 2 pax"), since the total is what gets paid and
    per-person is what price-comparison sites advertise.
  - `historical_best_price` is `MIN` over all rows and never recomputed, so
    changing a tracker's party size mid-life would compare unlike quantities
    forever. Either freeze party size after creation, or reset the tracker's
    history when it changes — do not silently mix.

### Fare brand + baggage comparability
- [ ] **Capture the fare brand, and constrain the search rather than parsing
  baggage.** Investigated 2026-08-11 against real data from both sources.

  **What exists:**
  - **Kayak** prints a fare brand per row — `Light`, `Basic`, `Economy Light`,
    `Economy Lite`, `Economy`, `Light + Economy Cabin` — right next to each
    price. It does **not** print a baggage allowance per row; the only bag text
    on the page is the *filter sidebar* ("Carry-on bag", "Checked bag") plus
    the disclaimer *"Prices are per person and do not include baggage fees."*
  - **Google/`fli`** exposes no baggage field on `FlightResult` or
    `FlightLeg` either. `BookingOption.fare_name` carries the brand, but only
    via `get_booking_options()` — an extra call per flight (already a separate
    TODO item above).

  **So baggage allowance is not readable from either source.** The robust move
  is to constrain the query so every returned price is comparable by
  construction, rather than parsing an allowance that isn't there:
  - `fli` accepts `FlightSearchFilters.bags` (`BagsFilter(carry_on=..,
    checked_bags=..)`) and, notably, `exclude_basic_economy: bool`.
  - Kayak's own UI has the equivalent filter ("Only show options with seat
    selection and carry-on bag"), so `_build_url` would need the matching
    parameter — **verify against a real render, do not guess the param name**.

  Storing `fare_brand` is still worth doing on its own: it is what makes the
  duplicate rows meaningful (see below), and it is the honest label for why a
  €641 fare undercuts a €715 one.

  **Sequencing note:** do this together with the passengers/ages item — bag
  rules matter most when travelling with a child, and both change
  `_build_url` and the `fli` filter construction, so doing them separately
  means touching the same code and invalidating captured samples twice.

- [x] **Duplicate Kayak rows** — Kayak lists one itinerary once per fare brand;
  `_first_carrier` collapses the carrier-list difference and `flight_key`
  carries no brand, so they arrived identical. Fixed 2026-08-11 by
  over-fetching `_OVERFETCH_ROWS` extra itineraries and collapsing rows
  identical in carrier + both times + price (`KayakSource._dedupe_rows`).
  Capturing `fare_brand` would make them distinguishable rather than
  duplicated, at which point the dedupe key should include it.

- [ ] **`FlightResult.self_transfer` is a first-class field in `fli`.** Google
  flags self-transfer itineraries natively, so the roadmap item below need not
  rely on scraping Kayak's `Self-transfer hack` label for the Google side.

### Self-transfer / "hacker" fares (currently excluded)
- [ ] **Optionally surface Kayak's "Self-transfer hack" itineraries.** These are
  two **separately ticketed** flights Kayak stitches together — e.g.
  `Arajet, Air Europa`, 3 stops via PUJ, €702 on 2026-08-11 while the cheapest
  normal GRU→ZRH fare was €784. They are genuinely printed on the page and pass
  every guard, so they were being stored as ordinary flights and, being
  cheapest, dominated `best_price` and `historical_best_price`. As of
  2026-08-11 `_strip_self_transfer_rows` removes them before extraction.

  Why they were excluded rather than kept: a missed connection is **not
  protected** (no through-checked bags, no rebooking), so the price is not
  comparable to a normal fare, and mixing the two into one all-time low makes
  the headline number unreachable in practice. They also appear inconsistently
  in Kayak's own inventory (present 00:43, gone 02:13), and never appeared in
  the user's own manual searches.

  If surfaced later, they need to stay *distinguishable*, not merged:
  - A `self_transfer` boolean on `flight_prices`, set by the extractor — not a
    string sniffed in the UI.
  - Excluded from `historical_best_price` by default, or that column has to
    become per-kind. It is `MIN` over all rows and never recomputed, so one
    stored hacker fare permanently lowers a tracker's all-time low.
  - A visible badge in the results table plus a filter toggle, defaulting off.
  - The extraction prompt currently never sees them; re-including them means
    the model must be asked for the flag explicitly, and `_validate` must
    ground it like any other field.

### Kayak: actively search next-day early-morning departures
- [ ] **A second Kayak request per cycle, for `depart_date + 1`, filtered down to
  early-morning-only rows.** Deferred 2026-08-13 alongside the night-rollover
  fix (`KayakSource._rebase_departure_date`, `CLAUDE.md`) — that fix only
  reclassifies a next-day departure that *already happened to appear* on
  `depart_date`'s own results page (Kayak's own behavior, unexplained, not
  something this project controls). It does nothing for a red-eye that Kayak
  only lists under `depart_date + 1`'s page and never surfaces on
  `depart_date`'s — those are invisible to the tracker today, rollover fix or
  not.

  Scope, roughly in dependency order:
  - `KayakSource.search` (or `_search_inner`) issues a second render/extract
    pass against `_build_url(..., depart_date + 1 day, ...)`, alongside the
    existing `depart_date` request.
  - Drop every row from that second pass whose departure hour is at or past
    `_NIGHT_ROLLOVER_CUTOFF_HOUR` — the second request exists only to catch
    the early-morning window, not to double-count that day's whole schedule.
  - Surviving rows get the same `_rebase_departure_date` treatment (bucket
    under `depart_date`) before merging into the one snapshot the first
    request produced — same reasoning as "Why Kayak shares the main
    snapshot" in CLAUDE.md: two Kayak snapshots on one cycle would be exactly
    the kind of split-view staleness the per-source blending work exists to
    avoid.
  - **This doubles Kayak's request volume per cycle** — real traffic against
    a bot-detecting site (see "Enabling Kayak on more trackers" in
    CLAUDE.md), on top of doubling LLM extraction cost. Given Kayak is
    currently enabled on a single tracker, weigh whether the early-morning
    window is worth a second full render+extract before widening rollout,
    rather than assuming it scales for free.
  - Google/fli is unaffected in scope — its `travel_date` param already
    constrains to the exact queried day, so there's no equivalent gap to
    close there, only Kayak's.

### Additional sources + expandable flight detail
- [ ] **Skyscanner as a third source, with an expandable per-row detail view.**
  Deferred 2026-08-12 alongside the same-price row collapse
  (`_group_duplicate_price_rows`, `backend/pages.py`) — that fix only merges
  rows sharing a `flight_key` when the price is *also* identical, which was
  enough for two sources (Google + Kayak) but won't hold once a third source
  can disagree in more ways than "matches" or "doesn't". Discussed and
  deliberately sequenced this way: designing the expand UI now, before
  Skyscanner exists, means guessing at data it may not even have (leg-level
  detail? a deep link? something Kayak's collapsed view doesn't print?).

  **Approach: decided 2026-08-15 — use the Kayak strategy.** `backend/sources/skyscanner.py`
  implementing `SearchSource`, rendered by a headful patchright Chromium in its
  own process and extracted by the LLM, opt-in per tracker and **not**
  registered in `get_sources()`, exactly as `KayakSource` is. Skyscanner is a
  bot-defended JS site with no usable free API, so the fli-style path is not
  available; plans 017-021 already paid the discovery cost for this shape and
  it works in production.

  **What is genuinely reusable, and what only looks reusable.** The generic
  machinery is already factored out and should be shared, not copied:
  `kayak_render.py` (takes a URL plus a config and returns body text —
  effectively source-agnostic already), `kayak_samples.py`, the `posix_spawn`
  worker seam, and the evasion bundle. Rename rather than duplicate.

  The *page heuristics* are the opposite: `_BLOCKED_MARKERS`,
  `_RESULT_MARKERS`, `_CURRENCY_MARKERS`, `_strip_placements`,
  `_strip_self_transfer_rows`, `_strip_nearby_airport_promos`,
  `_results_section` and the extraction prompt are all literal strings from
  Kayak's rendered page. **Copying them across gives false confidence** — they
  will silently match nothing, and a guard that matches nothing reports
  success. Each must be re-derived from real captured Skyscanner bodies, and
  the sample capture must be wired in from the first render, not added after
  a failure (the plan 018 lesson: five samples became permanently
  unclassifiable because nothing persisted the bodies).

  **Three infrastructure limits that only bite with a SECOND browser source:**
  - **The browser profile is single-writer.** Skyscanner needs its own
    `data/skyscanner-profile`, and its currency must be forced by driving that
    site's own picker UI — the `?currency=` URL parameter was confirmed *not*
    honoured on Kayak, and preferences are stored **per origin**. Assume
    nothing transfers; force it, then verify it by reading the rendered page
    back, which is a separate step from forcing.
  - **`_get_kayak_render_lock()` is one process-wide lock**, and the container
    limits (`1.5G` / `2.0` cpus, `shm_size: 1gb`) were measured for exactly one
    Chromium. Keep a single global "one browser at a time" lock across both
    sources rather than a lock per profile, or re-measure the limits first —
    two concurrent headful Chromiums on this LXC is an untested load.
  - **One LLM call per render, on a free tier.** A second source doubles the
    call volume against the same quota, so the cadences interact.

  **The per-tracker opt-in pattern does not survive a third source.**
  `trackers.kayak_enabled` + `kayak_next_due_at` is a column pair per source;
  Skyscanner would make it four columns, and Passengers is already adding
  columns to the same table. Move to a `tracker_sources` table (tracker_id,
  source, enabled, next_due_at) before adding the second pair, not after.

  **It will fork identity again unless the variant map is extended.**
  Skyscanner spells carriers its own way, and `normalize_airline`
  (`fingerprint.py`) only bridges names present in `AIRLINE_NAME_TO_CODE`.
  Expect a repeat of the `LATAM`/`LATAM Airlines` fork on first contact — the
  detection is the same query used in plan 024 Phase 4 (same snapshot, same
  clock times, different `flight_key`). Note that **adding map entries changes
  stored keys**, so it needs the backfill script re-run, and that is a data
  migration to schedule rather than a line to sneak in.
  - Replace the price-match merge with an always-merge-by-`flight_key`
    row: one row per physical flight, showing a price range (or the
    cheapest, clearly marked) when sources disagree, instead of either
    hiding the disagreement or listing several near-identical rows.
  - Add an expandable section per row (click/toggle) surfacing:
    - A per-source price breakdown, each with its own freshness/staleness —
      `source_freshness` already computes this per source in
      `_build_detail_context`, just not exposed per-row today.
    - Full multi-leg flight detail — the Flight column already crams
      multi-segment itineraries into one string (e.g. "IB 272+IB 1287");
      expand into per-leg carrier/flight-number/times instead of the
      joined string.
  - `_group_duplicate_price_rows` was written with this in mind: the merge
    step (group by `flight_key`) is already separate from the "only if
    price matches" decision, so extending it later is a criteria change,
    not a rewrite.
  - **Codeshare pairs are a second identity fork, same shape as the
    name-variant one Phase 4 fixed** (023's architectural finding, recorded
    2026-08-13). Two carriers selling seats on the *same physical flight*
    under different marketing flight numbers (e.g. an Iberia flight also sold
    as a British Airways codeshare) print different airline names *and*
    different flight numbers, so today they get two distinct `flight_key`s
    and never merge — unlike the `LATAM`/`LATAM Airlines` case, this one
    isn't solvable by a name→code map, since the two carriers are genuinely
    different sellers of the same seat. Belongs here rather than in Phase 4's
    scope because it's the same "one itinerary, several sellers" shape this
    expandable-detail view is designed for, and a codeshare pair would want
    the same per-source breakdown treatment as a genuine multi-source price
    disagreement.

### Database size: normalise first, then compress the series
- [ ] **Shrink the DB, cheapest and safest technique first.** Measured
  2026-08-15 against the live database — every number below is real, not an
  estimate.

  **Where the space actually is.** The file is 219 MB; `flight_prices` is
  182 MB of it (87%), indexes 23 MB, everything else under 1 MB. Growth is
  ~15,000 rows/day (6 trackers x ~100 rows x 24 cycles) ≈ 12 MB/day at the
  current per-row cost. Broken down by column:

  | column | size | distinct values |
  |---|---|---|
  | `legs_json` | **97 MB** (53% of the table) | **2,993** |
  | `booking_url` | **24 MB** | **30** |
  | `flight_key` | 11 MB | — |
  | departure+arrival times | 10 MB | — |
  | `airline` | 2 MB | — |

  **Technique 1 — normalise the two duplicated text columns. Do this first.**
  121 MB of the 182 MB table (66%) is the same handful of strings written over
  and over. `legs_json` holds 275,980 rows of just 2,993 distinct values, and
  crucially `COUNT(DISTINCT flight_key||legs_json)` is *also* 2,993 — the legs
  are a pure function of the flight, never varying per snapshot, so a side
  table keyed on `flight_key` is **exactly correct and completely lossless**.
  `booking_url` is worse: 276,493 rows holding **30** distinct strings (each
  source builds one search URL per tracker and repeats it on every row).

  This is the whole point of doing it first: it is lossless, it needs no
  decision about what history is worth keeping, it touches no read path that
  computes prices, and it is bigger than the technique below. **Note
  `legs_json` is currently written by every source and read by nothing** —
  but do NOT simply drop it: it is precisely the per-leg data the expandable
  row view above needs, so normalise it into a side table rather than
  deleting the only copy of it.

  **Technique 2 — run-length the price series (the original idea).** 141,910
  of 276,493 rows (**51.3%**) are interior points of a run where the same
  flight held the same price in the previous *and* next observation, so
  keeping only the first and last of each run preserves every price movement
  and every chart inflection.

  **The trap that makes this harder than it looks, and why it is second:**
  this app reads *the absence of a row from a snapshot* as a fact — it means
  "this flight is no longer offered", and that is what drives the `missing`
  delta and the blended per-source reconstruction. Delete an unchanged row and
  absence becomes ambiguous: was the flight gone, or merely unchanged? That
  ambiguity would land directly on the machinery plans 019/020 spent two weeks
  getting right. Any implementation therefore needs the run made *explicit* —
  an `observed_until` timestamp or an explicit run table — not rows silently
  removed. `historical_best_price` is safe either way (it is `MIN` over all
  rows, and first+last of a flat run preserves the minimum), but verify that
  claim against the real table before trusting it.

  **Technique 3 — retention.** Absorbs the old "Snapshot pruning" item: drop
  or downsample snapshots beyond some age. Least attractive of the three
  because it is the only one that destroys information the others preserve,
  so it should be the last resort, not the first move.

  **Housekeeping, independent of all of the above:** SQLite does not return
  freed pages to the filesystem without `VACUUM`, so none of this shrinks the
  file until it runs. Separately there are currently **6 database backups in
  `data/` (~1.1 GB)**, four of them superseded — more than the live database
  costs. Deleting those is the single cheapest disk win available and needs
  only a decision, not code.

  **Sequencing:** technique 1 is safe enough to do at any time and should
  happen before the table grows further. Technique 2 wants the identity and
  blending work to stay settled, so it should not land next to Passengers.

## Future (v2)
- [ ] **City name autocomplete** — replace raw text inputs with city name search + autocomplete (e.g. type "Barcelona" → suggests BCN). Needs an airport/city dataset.
- [ ] **Multicurrency** — Allow showing prices in any currency
- [ ] **Notification delivery** — transport layer (email, push, webhook). DB table + API + evaluation logic already exists.
- [ ] **Snapshot pruning** — moved into "Database size: normalise first, then compress the series" above (technique 3), where it sits alongside the two lossless techniques that should be tried before it.
- [ ] **Docker deployment** — single Dockerfile with uvicorn.
- [ ] **Authentication** — API key or basic auth if deployed publicly.