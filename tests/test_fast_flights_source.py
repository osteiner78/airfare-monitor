import json
import pytest
from unittest.mock import patch


def _leg_array(airline_code="IB", flight_number="622", airline_name="Iberia"):
    # Only indices consumed by FastFlightsSource._extract_flight_numbers matter (22);
    # the rest are filler since this fixture bypasses fast_flights.parser.parse entirely.
    return [None] * 22 + [[airline_code, flight_number, None, airline_name]]


def _payload(legs):
    flight = ["IB", ["Iberia"], legs]
    price_info = [[None, 175]]
    itinerary = [flight, price_info]
    return [None, None, None, [[itinerary]]]


# --- SearchSource protocol ---

async def test_fast_flights_satisfies_search_source_protocol():
    from backend.sources.fast_flights import FastFlightsSource
    from backend.sources.base import SearchSource
    source = FastFlightsSource()
    assert isinstance(source, SearchSource)


# --- _extract_flight_numbers: raw-payload recovery ---

def test_fast_flights_flight_number_recovered_from_raw_payload():
    from backend.sources.fast_flights import FastFlightsSource
    payload = _payload([_leg_array()])
    html = f'<html><body><script class="ds:1">data:{json.dumps(payload)}, sideChannel: {{}}}});</script></body></html>'
    numbers = FastFlightsSource._extract_flight_numbers(html)
    assert numbers == [["IB 622"]]


def test_fast_flights_flight_number_empty_when_index_22_missing_but_rest_parses():
    from backend.sources.fast_flights import FastFlightsSource
    short_leg = [None] * 5  # too short to have index 22
    payload = _payload([short_leg])
    html = f'<html><body><script class="ds:1">data:{json.dumps(payload)}, sideChannel: {{}}}});</script></body></html>'
    numbers = FastFlightsSource._extract_flight_numbers(html)
    assert numbers == [[""]]


# --- _map_result: field mapping ---

def test_fast_flights_maps_price_stops_duration_from_result():
    from backend.sources.fast_flights import FastFlightsSource
    from fast_flights.model import Airport, CarbonEmission, Flights, SimpleDatetime, SingleFlight

    leg1 = SingleFlight(
        from_airport=Airport(name="Geneva Airport", code="GVA"),
        to_airport=Airport(name="Madrid Airport", code="MAD"),
        departure=SimpleDatetime(date=[2026, 8, 20], time=[6, 10]),
        arrival=SimpleDatetime(date=[2026, 8, 20], time=[8, 15]),
        duration=125,
        plane_type="Airbus A320",
    )
    leg2 = SingleFlight(
        from_airport=Airport(name="Madrid Airport", code="MAD"),
        to_airport=Airport(name="Zurich Airport", code="ZRH"),
        departure=SimpleDatetime(date=[2026, 8, 20], time=[11, 40]),
        arrival=SimpleDatetime(date=[2026, 8, 20], time=[14]),  # ":00" omitted by Google
        duration=140,
        plane_type="Airbus A320",
    )
    flights = Flights(
        type="IB", price=175, airlines=["Iberia"], flights=[leg1, leg2],
        carbon=CarbonEmission(typical_on_route=43000, emission=212000),
    )

    class StubQuery:
        def url(self):
            return "https://www.google.com/travel/flights/search?tfs=stub"

    source = FastFlightsSource()
    result = source._map_result(flights, ["IB 622", "IB 629"], "EUR", StubQuery())

    assert result.source == "fast_flights"
    assert result.price == 175.0
    assert result.currency == "EUR"
    assert result.stops == 1
    assert result.duration_min == 265
    assert result.airline == "Iberia"
    assert result.flight_number == "IB 622+IB 629"
    assert result.departure_time == "2026-08-20T06:10:00"
    assert result.arrival_time == "2026-08-20T14:00:00"
    assert result.booking_url == "https://www.google.com/travel/flights/search?tfs=stub"


# --- failure modes ---

async def test_fast_flights_returns_empty_list_when_library_raises_not_found():
    from backend.sources.fast_flights import FastFlightsSource
    import fast_flights
    from fast_flights.exceptions import FlightsNotFound

    source = FastFlightsSource()
    with patch.object(fast_flights, "fetch_flights_html", return_value="<html></html>"), \
         patch.object(fast_flights.parser, "parse", side_effect=FlightsNotFound("no flights found")):
        result = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    assert result == []
    assert source.last_error_level == "WARNING"


async def test_fast_flights_returns_empty_list_and_records_error_when_search_raises_exception():
    from backend.sources.fast_flights import FastFlightsSource
    source = FastFlightsSource()
    with patch.object(source, "_fetch", side_effect=RuntimeError("network error")):
        result = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    assert result == []
    assert source.last_error == "RuntimeError: network error"
    assert source.last_error_level == "ERROR"


async def test_fast_flights_round_trip_not_supported_records_error():
    from backend.sources.fast_flights import FastFlightsSource
    source = FastFlightsSource()
    result = await source.search("GVA", "BCN", "2026-09-15", "2026-09-22", "EUR", 5)

    assert result == []
    assert "NotImplementedError" in source.last_error
    assert source.last_error_level == "ERROR"


# --- live search (requires network + fast_flights installed) ---

@pytest.mark.slow
async def test_real_fast_flights_search_returns_flight_results_for_valid_route():
    from backend.sources.fast_flights import FastFlightsSource
    from backend.sources.base import FlightResult
    source = FastFlightsSource()
    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)
    assert isinstance(results, list)
    if results:
        assert all(isinstance(r, FlightResult) for r in results)
        assert all(r.price > 0 for r in results)


# --- _to_iso: incomplete timestamps from Google's payload ---
# Observed in production 61 times between 2026-08-03 20:14:55 and
# 2026-08-04 23:00:31 across 4 trackers:
#   "fast_flights: TypeError: unsupported format string passed to
#    NoneType.__format__"
# _to_iso is the only place in this module applying a format spec ({:04d} /
# {:02d}), and Google intermittently returns a None component in a leg's
# date/time. The result was fatal to the WHOLE fetch, not just the bad leg:
# _map_result runs inside a list comprehension in _fetch, so one malformed
# timestamp made fast_flights return zero results and log an ERROR. Not
# reproducible on demand -- it depends on what Google serves -- so these
# drive the fix from the proven failure mode instead.

class _FakeDateTime:
    def __init__(self, date, time):
        self.date = date
        self.time = time


async def test_to_iso_formats_a_complete_timestamp():
    """NON-REGRESSION: the normal path must be untouched."""
    from backend.sources.fast_flights import FastFlightsSource
    dt = _FakeDateTime(date=(2026, 8, 21), time=(14, 35))
    assert FastFlightsSource._to_iso(dt) == "2026-08-21T14:35:00"


async def test_to_iso_treats_omitted_minute_as_zero():
    """NON-REGRESSION: Google omits the minute entirely when it is :00."""
    from backend.sources.fast_flights import FastFlightsSource
    dt = _FakeDateTime(date=(2026, 8, 21), time=(14,))
    assert FastFlightsSource._to_iso(dt) == "2026-08-21T14:00:00"


async def test_to_iso_treats_explicit_none_minute_as_zero():
    from backend.sources.fast_flights import FastFlightsSource
    dt = _FakeDateTime(date=(2026, 8, 21), time=(14, None))
    assert FastFlightsSource._to_iso(dt) == "2026-08-21T14:00:00"


async def test_to_iso_returns_empty_string_when_hour_is_none():
    """No fabricated midnight: departure_time feeds flight_key, so inventing
    00:00 would forge an identity. An empty string degrades cleanly -- the
    key stays airline+flight_number, and _split_timestamps already tolerates
    a missing timestamp."""
    from backend.sources.fast_flights import FastFlightsSource
    dt = _FakeDateTime(date=(2026, 8, 21), time=(None, 35))
    assert FastFlightsSource._to_iso(dt) == ""


async def test_to_iso_returns_empty_string_when_a_date_component_is_none():
    from backend.sources.fast_flights import FastFlightsSource
    for date in ((None, 8, 21), (2026, None, 21), (2026, 8, None)):
        dt = _FakeDateTime(date=date, time=(14, 35))
        assert FastFlightsSource._to_iso(dt) == ""


async def test_to_iso_returns_empty_string_when_time_is_absent_entirely():
    from backend.sources.fast_flights import FastFlightsSource
    dt = _FakeDateTime(date=(2026, 8, 21), time=())
    assert FastFlightsSource._to_iso(dt) == ""


async def test_to_iso_never_raises_for_any_none_shaped_input():
    """The contract that matters: one malformed leg must not be able to take
    down the entire fetch."""
    from backend.sources.fast_flights import FastFlightsSource
    shapes = [
        ((None, None, None), (None, None)),
        ((2026, 8, 21), (None,)),
        ((None, 8, 21), ()),
    ]
    for date, time in shapes:
        assert isinstance(FastFlightsSource._to_iso(_FakeDateTime(date, time)), str)
