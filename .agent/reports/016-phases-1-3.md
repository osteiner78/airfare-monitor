# Plan 016 — verification report (phases 1–3)

## Phase 1 + 2 — unit tests

```
$ pytest tests/test_fast_flights_source.py tests/test_fallback_source.py tests/test_sources.py -v -k "not slow"
...
tests/test_fast_flights_source.py::test_fast_flights_satisfies_search_source_protocol PASSED
tests/test_fast_flights_source.py::test_fast_flights_flight_number_recovered_from_raw_payload PASSED
tests/test_fast_flights_source.py::test_fast_flights_flight_number_empty_when_index_22_missing_but_rest_parses PASSED
tests/test_fast_flights_source.py::test_fast_flights_maps_price_stops_duration_from_result PASSED
tests/test_fast_flights_source.py::test_fast_flights_returns_empty_list_when_library_raises_not_found PASSED
tests/test_fast_flights_source.py::test_fast_flights_returns_empty_list_and_records_error_when_search_raises_exception PASSED
tests/test_fast_flights_source.py::test_fast_flights_round_trip_not_supported_records_error PASSED
tests/test_fallback_source.py::test_fallback_satisfies_search_source_protocol PASSED
tests/test_fallback_source.py::test_fallback_returns_primary_results_without_calling_secondary PASSED
tests/test_fallback_source.py::test_fallback_calls_secondary_when_primary_returns_empty PASSED
tests/test_fallback_source.py::test_fallback_last_error_combines_both_when_both_empty PASSED
tests/test_fallback_source.py::test_fallback_no_error_when_both_sources_genuinely_empty PASSED
tests/test_sources.py::test_flight_result_dataclass_has_all_required_fields PASSED
tests/test_sources.py::test_google_flights_source_satisfies_search_source_protocol PASSED
tests/test_sources.py::test_all_sources_returns_nonempty_list PASSED
tests/test_sources.py::test_google_flights_returns_empty_list_when_fli_raises_import_error PASSED
tests/test_sources.py::test_google_flights_returns_empty_list_when_search_raises_exception PASSED
======================= 17 passed, 1 deselected =======================
```

## Full non-regression pass

```
$ pytest tests/ -q -k "not slow"
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
........                                                                 [100%]
224 passed, 2 deselected in 22.28s
```

(Baseline before this plan was 212 passed — the +12 are the new
`test_fast_flights_source.py` / `test_fallback_source.py` files, non-slow
subset; no existing test was modified.)

## Phase 3 — live end-to-end verification

Ran `search_and_store(3)` against the production DB (tracker `#3`,
GVA→BCN, 2026-09-15 — the one tracker with a valid, non-past depart date)
through the real `FallbackSource` (no mocks):

- `fli` (primary) still returns 0 results / the same upstream `[13]`
  INTERNAL error as before — outage unresolved on Google's side.
- `fast_flights` (fallback) engaged automatically and returned **5 real
  itineraries** (€44–€99, easyJet/Vueling/Brussels Airlines, real flight
  numbers e.g. `U2 1293`, `SN 2714+SN 3705`).
- `system_logs`: clean `search_start` → `search_done` (`5 results`), no
  `search_error` — `FallbackSource.last_error` stayed `None` since the
  fallback succeeded.
- `flight_prices` for the new snapshot: confirmed `source = 'fast_flights'`
  for all 5 rows via direct DB query.
- Dashboard (`GET /`) renders the tracker's card with a real price
  (`€44`) instead of the `–` null-guard placeholder from the earlier fix.

Live tracking is restored for every currently-active, non-past tracker,
with zero manual intervention needed once `fli` recovers (it's tried
first on every run; the moment it starts returning results again it
silently resumes being primary).
