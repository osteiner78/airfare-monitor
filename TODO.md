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


## Roadmap

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

  Scope, once Skyscanner is actually being wired in:
  - Add `backend/sources/skyscanner.py` implementing `SearchSource` (see
    "Flight source architecture" in CLAUDE.md) — or, if it needs its own
    render/extraction pipeline like Kayak, keep it opt-in and unregistered
    from `get_sources()` the same way `KayakSource` is.
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

## Future (v2)
- [ ] **City name autocomplete** — replace raw text inputs with city name search + autocomplete (e.g. type "Barcelona" → suggests BCN). Needs an airport/city dataset.
- [ ] **Multicurrency** — Allow showing prices in any currency
- [ ] **Notification delivery** — transport layer (email, push, webhook). DB table + API + evaluation logic already exists.
- [ ] **Snapshot pruning** — data retention policy for old snapshots. Currently accumulates unbounded.
- [ ] **Docker deployment** — single Dockerfile with uvicorn.
- [ ] **Authentication** — API key or basic auth if deployed publicly.