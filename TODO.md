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

## Future (v2)
- [ ] **City name autocomplete** — replace raw text inputs with city name search + autocomplete (e.g. type "Barcelona" → suggests BCN). Needs an airport/city dataset.
- [ ] **Multicurrency** — Allow showing prices in any currency
- [ ] **Notification delivery** — transport layer (email, push, webhook). DB table + API + evaluation logic already exists.
- [ ] **Snapshot pruning** — data retention policy for old snapshots. Currently accumulates unbounded.
- [ ] **Docker deployment** — single Dockerfile with uvicorn.
- [ ] **Authentication** — API key or basic auth if deployed publicly.