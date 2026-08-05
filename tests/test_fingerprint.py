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


# --- key structure ---
# flight_key intentionally excludes `source` as of plan 017 (Kayak as a
# concurrent, non-fallback source): the same physical flight quoted by two
# different sources in one snapshot must resolve to the same identity, or
# the missing/new-flight diff and chart lines treat one flight as two.
# As of plan 019 it also excludes `flight_number`: Kayak's collapsed list
# view prints no flight number on any row (confirmed across all 9 captured
# bodies in data/kayak-samples/), so the model invented "", "N/A", "unknown"
# and "AT" for one physical flight across runs -- four identities for one
# flight, and never equal to Google's "TP 84" for the same flight either.
# The format is now `airline|departure_time|arrival_time`; the earlier
# 4-part source-prefixed and 3-part flight-number forms are deliberately
# removed rather than kept as regression anchors.

async def test_flight_key_has_three_parts_of_airline_and_both_times():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(
        airline="LX",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T09:00:00+02:00",
    ))
    parts = key.split("|")
    assert len(parts) == 3
    assert parts[0] == "lx"
    assert parts[1] == "2026-06-15T07:30:00+02:00"
    assert parts[2] == "2026-06-15T09:00:00+02:00"


async def test_flight_key_excludes_flight_number():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(flight_number="LX1234"))
    assert "LX1234" not in key


async def test_flight_key_does_not_start_with_source_name():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(source="google_flights"))
    assert not key.startswith("google_flights|")


async def test_flight_key_is_unchanged_by_the_flight_number_field():
    """The identity must not move when only the display-only field moves --
    this is the exact fragmentation plan 019 exists to stop."""
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(flight_number="TP 84"))
    key_b = make_flight_key(make_result(flight_number="N/A"))
    key_c = make_flight_key(make_result(flight_number=""))
    assert key_a == key_b == key_c


# --- multi-leg itineraries ---

async def test_multistop_key_keeps_the_joined_airline_segment():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="LH+OS", flight_number="LH1234+OS5678", stops=1))
    parts = key.split("|")
    assert parts[0] == "lh+os"


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


async def test_flight_key_differs_for_same_airline_and_departure_but_different_arrival():
    """The routing-collision case that ruled out option B (airline|departure
    alone): one carrier, one departure minute, two itineraries that route
    differently and land at different times. Collapsing these would merge two
    genuinely different products -- and their prices -- into one series."""
    from backend.fingerprint import make_flight_key
    key_direct = make_flight_key(make_result(
        airline="TAP Air Portugal",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T09:00:00+02:00",
    ))
    key_via_lis = make_flight_key(make_result(
        airline="TAP Air Portugal",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T18:45:00+02:00",
    ))
    assert key_direct != key_via_lis


# --- airline normalisation ---

async def test_flight_key_normalises_airline_casing_and_whitespace():
    """Kayak prints "GOL" where Google prints "Gol" (verified against the real
    captured bodies and the live flight_prices table), so a case-sensitive
    airline segment forks one flight in two across sources."""
    from backend.fingerprint import make_flight_key
    key_kayak = make_flight_key(make_result(source="kayak", airline="TAP AIR PORTUGAL"))
    key_google = make_flight_key(make_result(source="google_flights", airline="Tap Air Portugal"))
    key_padded = make_flight_key(make_result(airline="  Tap   Air  Portugal  "))
    assert key_kayak == key_google == key_padded


async def test_flight_key_still_separates_genuinely_different_airlines():
    """Guards against a normalisation so aggressive it merges distinct carriers."""
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(airline="Gol"))
    key_b = make_flight_key(make_result(airline="Azul"))
    assert key_a != key_b


# --- cross-source identity (the point of plan 019 phase 2) ---

async def test_flight_key_matches_across_sources_when_one_lacks_a_flight_number():
    """Plan 017 phase 1 dropped `source` from the key so one physical flight
    quoted by two sources collapses to one identity. That could never work for
    Kayak, whose list view prints no flight number: "TAP Air Portugal|TP 84|..."
    (Google) can never equal "TAP Air Portugal||..." (Kayak). With the number
    out of the key, they finally agree."""
    from backend.fingerprint import make_flight_key
    key_google = make_flight_key(make_result(
        source="google_flights",
        airline="Tap Air Portugal",
        flight_number="TP 84",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T18:45:00+02:00",
    ))
    key_kayak = make_flight_key(make_result(
        source="kayak",
        airline="TAP AIR PORTUGAL",
        flight_number="",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T18:45:00+02:00",
    ))
    assert key_google == key_kayak


async def test_flight_key_identical_across_different_sources_for_same_physical_flight():
    from backend.fingerprint import make_flight_key
    key_google = make_flight_key(make_result(source="google_flights"))
    key_fast_flights = make_flight_key(make_result(source="fast_flights"))
    key_kayak = make_flight_key(make_result(source="kayak"))
    assert key_google == key_fast_flights == key_kayak


# --- failure modes ---

async def test_key_with_empty_airline_still_produces_three_parts():
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(airline="", flight_number=""))
    assert len(key.split("|")) == 3


async def test_key_with_empty_airline_still_differs_by_departure_time():
    """Guards against an empty-field key collapsing two unrelated results
    (e.g. two totally unparsed rows) into one identity purely by accident."""
    from backend.fingerprint import make_flight_key
    key_a = make_flight_key(make_result(
        airline="", flight_number="", departure_time="2026-06-15T07:30:00+02:00"))
    key_b = make_flight_key(make_result(
        airline="", flight_number="", departure_time="2026-06-15T20:00:00+02:00"))
    assert key_a != key_b


async def test_key_with_empty_departure_time_still_produces_three_parts():
    """33 of the 165,656 production rows carry an empty departure_time; the
    backfill lands them on a 2-separator key and make_flight_key must agree
    rather than producing a differently-shaped key for the same data."""
    from backend.fingerprint import make_flight_key
    key = make_flight_key(make_result(departure_time="", arrival_time=""))
    assert len(key.split("|")) == 3
