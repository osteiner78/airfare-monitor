# TODO

## Bugs
- [ ] **`GET /api/trackers` returns `active` as int** — list endpoint bypasses `TrackerResponse` Pydantic model, serializes `active` as `1`/`0` instead of `true`/`false`.

## Improvements
- [ ] **Design polish** — pass through Claude Design for UI/UX improvements.
- [ ] **Bundle Chart.js locally** — currently loaded from jsdelivr CDN. Bundle for offline use.
- [x] **Replace airline codes with airline logos/icons**


### Dashboard
- [ ] **Trackers list**: Include historical best price



### Tracker details

#### Tracker details box
- [ ] **Details box**: move ACTIVE badge and pause+delete buttons to the right side. Leave Google Flighs and Search Now button on the right side

#### Chart
- [] **Fix chart tooltip** — change times to local times, add currency to price
- [x] **Fix chart tooltip** — tooltip shows raw price without currency symbol and uses epoch timestamps. Should show formatted date + currency (e.g., "May 31 19:44 — 102.00 EUR").

#### Table
- [ ] Change "Current Results" to "Last prices fetched (<time> ago)"
- [ ] Add a selection box besides all flights, when checked it adds it to the chart -> will require storing historical prices for all flights
- [ ] **Remove Arrival Date**: leave only departure date. If arrival date is next day, add string "(+1 day)" beside the arrival time
- [ ] **Fetch per-flight booking URLs** — using fli's `get_booking_options()`.




## Future (v2)
- [ ] **City name autocomplete** — replace raw text inputs with city name search + autocomplete (e.g. type "Barcelona" → suggests BCN). Needs an airport/city dataset.
- [ ] **Multicurrency** — Allow showing prices in any currency
- [ ] **Notification delivery** — transport layer (email, push, webhook). DB table + API + evaluation logic already exists.
- [ ] **Snapshot pruning** — data retention policy for old snapshots. Currently accumulates unbounded.
- [ ] **Docker deployment** — single Dockerfile with uvicorn.
- [ ] **Authentication** — API key or basic auth if deployed publicly.
