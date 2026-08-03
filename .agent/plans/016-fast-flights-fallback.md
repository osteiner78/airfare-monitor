# Plan 016 — `fast-flights` as primary source, `fli` as fallback

## Context

`fli` (PyPI package `flights`) has been the sole flight-data source since v1. As of
**2026-08-02 21:27** it started returning zero results for every tracker,
every route. This plan follows on from the same-day fix that made search
failures visible on `/monitor` instead of being silently swallowed as
"0 results" (see `backend/sources/google_flights.py` `last_error` /
`last_error_level`, committed `541da65`).

## Investigation (done, findings below)

**Root cause of the `fli` outage — confirmed, external, not fixable in this repo.**
`fli` calls Google's internal `GetShoppingResults` batchexecute RPC
(`https://www.google.com/_/FlightsFrontendUi/data/.../GetShoppingResults`).
Reproduced the raw HTTP call directly (bypassing `fli`'s own exception
handling) for two unrelated routes (GVA→ZRH, JFK→LAX): both return
**HTTP 200** with a Google RPC-level error payload instead of data:
```
)]}'
[["wrb.fr",null,null,null,null,[13]], ...]
```
`[13]` is gRPC `INTERNAL`. Same result for both routes → global, not
route-specific. `fli` is already at the latest PyPI release (0.9.0, confirmed
via `pip index versions` / PyPI JSON API — no newer release exists). The
GitHub `main` branch is ahead at unreleased `0.10.0`, but a matching open
issue, [punitarani/fli#200](https://github.com/punitarani/fli/issues/200)
("Flights search returns no results and Python API returns `None`",
opened June 2026, reporter already on `0.10.0`, no maintainer response as
of today) confirms the unreleased branch doesn't fix this either. This is
an unresolved upstream break, most likely on Google's side, with no ETA.

**`fast-flights` (`AWeirdDev/flights`, PyPI package `fast-flights`) — tested, works right now.**
It hits a *different* Google endpoint — `GET https://www.google.com/travel/flights/search?tfs=...`
(protobuf query encoded directly in the URL, the same URL a browser would
load) — rather than the batchexecute RPC. Tested live against the exact
two routes that are dead in `fli`:

| Route | Date | `fli` | `fast-flights` |
|---|---|---|---|
| GVA→ZRH | 2026-08-20 | `[13]` INTERNAL, 0 results | **9 real itineraries**, €175–€584 |
| JFK→LAX | 2026-09-15 | `[13]` INTERNAL, 0 results | **29 real itineraries**, $178+ |

No proxy, no auth, ~2s per query. Same long-term risk profile as `fli`
(undocumented format, MIT license, ~1.3k stars, actively developed) — it
can break too, just not from *this* specific Google-side change, since
it's a different request path entirely.

**Decision (user): `fli` stays primary, `fast-flights` is the fallback.**
Even though `fli` is the one currently broken — reasoning is `fli`'s
integration is more mature (2 months of production history, richer native
field mapping) and may recover on its own if Google reverts the change or
`fli` patches around it. `fast-flights` only gets called when `fli` comes
back empty, which today means every run, restoring live tracking, but
`fli` is tried first on every search so it silently resumes being primary
the moment Google unbreaks it — no code change needed to "switch back."

### Field-mapping gap — resolved, flight numbers ARE recoverable

Initial read of `fast-flights`' public API (`Flights`/`SingleFlight`
dataclasses) suggested no flight number was exposed, only an itinerary
`type` code. Checked whether it's really absent or just unexposed by
fetching the raw HTML (`fast_flights.fetch_flights_html(q)`) and inspecting
the underlying JSON payload the library's own parser reads
(`payload[3][0][i][0][2][j]` per itinerary `i` / leg `j`). Index `22` of
each leg's raw array — currently unused by the library's `parse_js` — is
`[airline_code, flight_number, null, airline_name]`, e.g.
`["IB", "622", None, "Iberia"]`, `["LH", "2383", None, "Lufthansa"]` for a
connection. Verified present and non-null on **100% of legs** across two
routes (GVA→ZRH: 13/13 legs across 9 itineraries; JFK→LAX: 32/32 legs
across 29 itineraries, including multi-carrier connections).

**Implementation implication:** our `fast_flights.py` source will fetch
the HTML once via `fast_flights.fetch_flights_html(q)`, get the typed
`ResultList` from the library's own `fast_flights.parser.parse(html)` for
everything else (price, route, duration, carbon — don't re-derive
maintained logic), and separately re-walk the same raw JSON **only** for
this one field, zipping `(airline_code, flight_number)` per leg back onto
the parsed results by index. This duplicates one field's worth of
index-based parsing (fragile to a Google format change, like the rest of
`fast-flights` already is) in exchange for full parity with `fli`'s
`flight_number` field — no more field-mapping degradation versus `fli`.

| `FlightResult` field | From `fli` | From `fast-flights` |
|---|---|---|
| `price`, `duration_min`, `stops`, `airline` | direct | derivable (stops = `len(legs)-1`, duration = sum of leg durations, airline = `airlines[0]`) |
| `currency` | per-result from Google | not per-result — pass through the query's requested currency |
| `flight_number` | real (e.g. `"LX 1234"`) | real, via the raw-payload extraction above (e.g. `"IB 622+IB 629"` joined per leg, matching `fli`'s `"+"`-joined convention) |
| `booking_url` | generic Google Flights search link | `query.url()` — a **precise deep link** to this exact search, better than `fli`'s |

---

## Design

Keep `scheduler.py`'s "aggregate every registered source" loop untouched —
the pluggable-source architecture (`backend/sources/`, one file per
source, register in `__init__.py`) doesn't currently have a concept of
priority/fallback between sources, and changing that loop would affect any
future third source too. Instead, add a **new self-contained source**,
`FallbackSource`, that composes the two existing sources internally: try
`fli` (`GoogleFlightsSource`) first — it's primary — and only call
`fast_flights` (`FastFlightsSource`) if `fli` comes back empty.
`get_sources()` then returns a single `[FallbackSource()]`. This means
zero changes to `scheduler.py` — the `last_error` / `last_error_level`
surfacing added in `541da65` keeps working unmodified, since
`FallbackSource` exposes the same `last_error` contract (set to a combined
message only when *both* sources fail).

---

## Phase 1 — `backend/sources/fast_flights.py`

### Intent
A new, self-contained `SearchSource` implementation wrapping the
`fast-flights` package, mirroring `google_flights.py`'s shape (constructor
with `last_error`/`last_error_level`, `search()` never raises).

### Tasks
1.1 Add `fast-flights` to `requirements.txt`.
1.2 `FastFlightsSource.__init__`: same `last_error: str | None`,
    `last_error_level: str = "ERROR"` pattern as `GoogleFlightsSource`.
1.3 `search()`: build a `fast_flights.Query` via `create_query()` from
    `origin`/`dest`/`depart_date`/`return_date`/`currency`/`top_n`
    (`max_stops` left unset). Fetch via `asyncio.to_thread(fast_flights.fetch_flights_html,
    q)` (sync, same `to_thread` pattern as `fli`'s `client.search`) to get
    the raw HTML once.
1.4 Parse twice from the same HTML: `fast_flights.parser.parse(html)` for
    the typed `ResultList` (price/route/duration/carbon — reuse the
    library's maintained logic), and a small local helper that re-walks
    the same `ds:1` JSON (`payload[3][0][i][0][2][j][22]`) to pull
    `(airline_code, flight_number)` per leg `j` of itinerary `i`, in the
    same iteration order the library uses — see Investigation above for
    the confirmed index. Zip the two by `(i, j)` position.
1.5 Catch `fast_flights.exceptions.FlightsNotFound` (or whatever the
    library raises for "no results") and treat as a clean empty result —
    **not** an error (mirrors a route genuinely having no flights).
1.6 Catch any other `Exception` (including a shape change in the index-22
    extraction — e.g. `IndexError`/`TypeError` on the raw payload) →
    set `last_error`/`last_error_level = "ERROR"`, return `[]` (matches
    `google_flights.py`'s contract). If index 22 shape-shifts but the rest
    of the payload still parses, degrade gracefully: log the flight-number
    extraction failure but still return priced results with
    `flight_number=""` rather than dropping the whole search — don't let
    one field's fragility take down an otherwise-working fetch.
1.7 `_map_result()`: map one `fast_flights.Flights` (+ its recovered flight
    numbers) → `FlightResult` per the table above. `source="fast_flights"`.
    `flight_number` = `"+".join(f"{code} {num}" for code, num in ...)` per
    leg, matching `fli`'s `"+"`-joined convention. `booking_url = q.url()`.
1.8 `return_date` (round-trip): confirm `create_query(trip="round-trip",
    flights=[outbound_query, inbound_query])` shape — check the library's
    round-trip example before wiring; if unsupported cleanly, raise
    `NotImplementedError` inside `_fetch` for round-trip and let the outer
    `except Exception` degrade it to a normal empty-result-with-error-log
    rather than crashing (no tracker in this DB currently uses
    `return_date`, so low urgency — confirm during implementation, don't
    guess).

### Files
- New: `backend/sources/fast_flights.py`
- Modify: `requirements.txt`

### Tests (new: `tests/test_fast_flights_source.py`, mirroring `tests/test_sources.py`'s existing `google_flights` failure-mode tests)
- `test_fast_flights_satisfies_search_source_protocol`
- `test_fast_flights_maps_price_stops_duration_from_result`
- `test_fast_flights_flight_number_recovered_from_raw_payload` (fixture HTML with a known index-22 value → asserts the real `"IB 622"`-style number, not the `type` code)
- `test_fast_flights_flight_number_empty_when_index_22_missing_but_rest_parses` (degraded-payload fixture — still returns priced results)
- `test_fast_flights_returns_empty_list_when_library_raises_not_found` (no error logged — legitimate empty)
- `test_fast_flights_returns_empty_list_and_records_error_when_search_raises_exception`
- `@pytest.mark.slow test_real_fast_flights_search_returns_results_for_valid_route` (network, mirrors the existing `fli` slow test)

---

## Phase 2 — `backend/sources/fallback.py` + registration

### Intent
Compose `FastFlightsSource` (primary) and `GoogleFlightsSource` (fallback)
behind one `SearchSource`. Only call the fallback when the primary returns
zero results.

### Tasks
2.1 `FallbackSource.__init__`: instantiate both sub-sources; expose
    `last_error`/`last_error_level` (same contract).
2.2 `search()`: call primary; if non-empty, return immediately (fallback
    never invoked — no wasted request). If empty, record primary's
    `last_error` (if any), call fallback, return its results.
2.3 If **both** are empty: combine into one message, e.g.
    `"fast_flights: <reason>; fli: <reason>"`, level = `ERROR` if either
    sub-source's level was `ERROR`, else `WARNING`.
2.4 `backend/sources/__init__.py::get_sources()` → `[FallbackSource()]`.

### Files
- New: `backend/sources/fallback.py`
- Modify: `backend/sources/__init__.py`

### Tests (new: `tests/test_fallback_source.py`)
- `test_fallback_returns_primary_results_without_calling_secondary` (mock both; assert secondary's `search` not called when primary returns data)
- `test_fallback_calls_secondary_when_primary_returns_empty`
- `test_fallback_last_error_combines_both_when_both_empty`
- `test_fallback_satisfies_search_source_protocol`

NON-REGRESSION: full `tests/test_sources.py` (existing `fli`-only tests) must keep passing unmodified — `GoogleFlightsSource` itself isn't touched in this plan.

---

## Phase 3 — Verify end-to-end against the live DB

### Intent
Confirm the fallback actually restores live tracking for the currently-broken trackers, without a schema or data change.

### Tasks
3.1 In the running Active-dev container, manually trigger `search_and_store` for tracker `#3` (the one currently-valid tracker) and confirm a real non-zero `snapshot.results_count` plus a `search_done` log — not `search_error`.
3.2 Check `/monitor` renders cleanly (no leftover `WARNING`/`ERROR` for that tracker on the next natural interval tick).
3.3 Leave the 9 auto-paused past-date trackers alone (out of scope — plan 015-adjacent work, not this plan).

### Verification command (per-phase, per `CLAUDE.md` convention)
```bash
pytest tests/test_fast_flights_source.py tests/test_fallback_source.py tests/test_sources.py -v -k "not slow"
pytest tests/ -v -k "not slow"   # full non-regression pass
```
Paste output into `.agent/reports/016-phase-N.md` per phase, per project convention.

---

## Decisions (confirmed with user, 2026-08-03)

1. Flight-number gap: resolved, not accepted as a degradation — recovered
   from the raw payload (see Investigation above).
2. Priority: **`fli` primary, `fast-flights` fallback** (reverse of the
   initial proposal — `fli` kept primary for its maturity/history despite
   currently being down; `fast-flights` only engages when `fli` is empty).
3. New runtime dependency (`fast-flights` in `requirements.txt`): approved.

Implementing phases 1–3 in order, running the test suite after each.
