# TODO

## Bugs

- [ ] **`GET /api/trackers` returns `active` as int** — list endpoint bypasses `TrackerResponse` Pydantic model, serializes `active` as `1`/`0` instead of `true`/`false`.

## Improvements

- [ ] **City name autocomplete** — replace raw text inputs with city name search + autocomplete (e.g. type "Barcelona" → suggests BCN). Needs an airport/city dataset.
- [ ] **Design polish** — pass through Claude Design for UI/UX improvements.
- [ ] **Bundle Chart.js locally** — currently loaded from jsdelivr CDN. Bundle for offline use.
- [ ] **Replace airline codes with airline logos/icons**
- [ ] **Fetch per-flight booking URLs** — using fli's `get_booking_options()`.
- [ ] **Fix chart tooltip** — tooltip shows raw price without currency symbol and uses epoch timestamps. Should show formatted date + currency (e.g., "May 31 19:44 — 102.00 EUR").

## Future (v2)

- [ ] **Notification delivery** — transport layer (email, push, webhook). DB table + API + evaluation logic already exists.
- [ ] **Snapshot pruning** — data retention policy for old snapshots. Currently accumulates unbounded.
- [ ] **Docker deployment** — single Dockerfile with uvicorn.
- [ ] **Authentication** — API key or basic auth if deployed publicly.
