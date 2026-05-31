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

async def test_nonstop_key_contains_four_pipe_separated_parts():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result())
    parts = key.split("|")
    assert len(parts) == 4


async def test_nonstop_key_starts_with_source_name():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(source="google_flights"))
    assert key.startswith("google_flights|")


async def test_nonstop_key_contains_airline_and_flight_number():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LX", flight_number="LX1234"))
    parts = key.split("|")
    assert parts[1] == "LX"
    assert parts[2] == "LX1234"


# --- multistop key structure ---

async def test_multistop_key_joins_airlines_with_plus():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LH+OS", flight_number="LH1234+OS5678", stops=1))
    parts = key.split("|")
    assert "+" in parts[1]
    assert parts[1] == "LH+OS"


async def test_multistop_key_joins_flight_numbers_with_plus():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LH+OS", flight_number="LH1234+OS5678", stops=1))
    parts = key.split("|")
    assert parts[2] == "LH1234+OS5678"


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


# --- failure modes ---

async def test_key_with_empty_airline_still_produces_four_parts():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="", flight_number=""))
    assert len(key.split("|")) == 4
