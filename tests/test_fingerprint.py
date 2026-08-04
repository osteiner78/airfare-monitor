import pytest


def make_result(**overrides):
    from backend.sources.base import FlightResult
    defaults = dict(
        source="google_flights",
        price=199.0,
        currency="EUR",
        duration_min=90,
        stops=0,
        airline="LX",
        flight_number="LX1234",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T09:00:00+02:00",
        legs_json="[]",
        booking_url="https://example.com",
    )
    defaults.update(overrides)
    return FlightResult(**defaults)


# --- nonstop key structure ---
# flight_key intentionally excludes `source` as of plan 017 (Kayak as a
# concurrent, non-fallback source): the same physical flight quoted by two
# different sources in one snapshot must resolve to the same identity, or
# the missing/new-flight diff and chart lines treat one flight as two.
# Superseded by plan 017 — this file was previously the anchor for a
# 4-part, source-prefixed key (`google_flights|LX|LX1234|...`); that
# format and its `test_nonstop_key_starts_with_source_name` /
# `test_nonstop_key_contains_four_pipe_separated_parts` tests are
# deliberately removed, not preserved as regression anchors.

async def test_nonstop_key_contains_three_pipe_separated_parts():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result())
    parts = key.split("|")
    assert len(parts) == 3


async def test_nonstop_key_does_not_start_with_source_name():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(source="google_flights"))
    assert not key.startswith("google_flights|")


async def test_nonstop_key_contains_airline_and_flight_number():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LX", flight_number="LX1234"))
    parts = key.split("|")
    assert parts[0] == "LX"
    assert parts[1] == "LX1234"


# --- multistop key structure ---

async def test_multistop_key_joins_airlines_with_plus():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LH+OS", flight_number="LH1234+OS5678", stops=1))
    parts = key.split("|")
    assert "+" in parts[0]
    assert parts[0] == "LH+OS"


async def test_multistop_key_joins_flight_numbers_with_plus():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LH+OS", flight_number="LH1234+OS5678", stops=1))
    parts = key.split("|")
    assert parts[1] == "LH1234+OS5678"


# --- determinism ---

async def test_same_flight_result_produces_same_key_on_repeated_calls():
    from backend.fingerprint import make_flight_key
    result = make_result()
    assert make_flight_key(result) == make_flight_key(result)


async def test_different_departure_times_produce_different_keys():
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(departure_time="2026-06-15T07:30:00+02:00"))
    key_b = make_flight_key(make_result(departure_time="2026-06-15T10:00:00+02:00"))
    assert key_a != key_b


# --- cross-source identity (new behavior, plan 017) ---

async def test_flight_key_identical_across_different_sources_for_same_physical_flight():
    """The core point of plan 017 phase 1: fli, fast_flights, and kayak quoting
    the same airline/flight_number/departure_time must produce one shared key,
    so cross-source dedup (cheapest wins) and chart/history continuity work."""
    from backend.fingerprint import make_flight_key
    key_google = make_flight_key(make_result(source="google_flights"))
    key_fast_flights = make_flight_key(make_result(source="fast_flights"))
    key_kayak = make_flight_key(make_result(source="kayak"))
    assert key_google == key_fast_flights == key_kayak


async def test_flight_key_still_differs_for_genuinely_different_flights_from_same_source():
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(source="kayak", flight_number="TP84"))
    key_b = make_flight_key(make_result(source="kayak", flight_number="TP88"))
    assert key_a != key_b


# --- failure modes ---

async def test_key_with_empty_airline_still_produces_three_parts():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="", flight_number=""))
    assert len(key.split("|")) == 3


async def test_key_with_empty_airline_and_flight_number_still_differs_by_departure_time():
    """Guards against an empty-field key collapsing two unrelated results
    (e.g. two totally unparsed rows) into one identity purely by accident."""
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(airline="", flight_number="", departure_time="2026-06-15T07:30:00+02:00"))
    key_b = make_flight_key(make_result(airline="", flight_number="", departure_time="2026-06-15T20:00:00+02:00"))
    assert key_a != key_b
