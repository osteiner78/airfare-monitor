"""Plan 028 Phase 1 — SearchQuery replaces the positional argument list.

NEW-BEHAVIOR: SearchQuery itself.
NON-REGRESSION: every source still satisfies the protocol, and FlightResult is
untouched. Those two must pass before AND after the refactor -- they are the
anchor proving the seam moved without the sources changing meaning.

Option C was chosen over adding a seventh positional argument because fare
brand, baggage and cabin class are all queued behind Passengers, and each would
otherwise repeat the same sweep across 13 test files.
"""


# --- NEW BEHAVIOR ---

def test_search_query_carries_every_field_the_old_signature_had():
    from backend.sources.base import SearchQuery
    query = SearchQuery(
        origin="GRU",
        dest="ZRH",
        depart_date="2026-08-21",
        return_date=None,
        currency="EUR",
        top_n=5,
    )
    assert (query.origin, query.dest, query.depart_date,
            query.return_date, query.currency, query.top_n) == (
        "GRU", "ZRH", "2026-08-21", None, "EUR", 5)


def test_search_query_is_frozen():
    import dataclasses
    import pytest
    from backend.sources.base import SearchQuery
    query = SearchQuery(origin="GRU", dest="ZRH", depart_date="2026-08-21",
                        return_date=None, currency="EUR", top_n=5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        query.origin = "CGH"


def test_a_round_trip_query_keeps_its_return_date():
    from backend.sources.base import SearchQuery
    query = SearchQuery(origin="GRU", dest="ZRH", depart_date="2026-08-21",
                        return_date="2026-09-04", currency="EUR", top_n=5)
    assert query.return_date == "2026-09-04"


def test_top_n_of_zero_is_preserved_rather_than_defaulted():
    """Sources decide what top_n=0 means; the query must not silently rewrite
    it, or a caller's explicit choice disappears between layers."""
    from backend.sources.base import SearchQuery
    query = SearchQuery(origin="GRU", dest="ZRH", depart_date="2026-08-21",
                        return_date=None, currency="EUR", top_n=0)
    assert query.top_n == 0


def test_an_empty_currency_is_preserved_rather_than_defaulted():
    """kayak._build_url already falls back to USD on an empty currency; that
    decision belongs to the source, not to the query object."""
    from backend.sources.base import SearchQuery
    query = SearchQuery(origin="GRU", dest="ZRH", depart_date="2026-08-21",
                        return_date=None, currency="", top_n=5)
    assert query.currency == ""


# --- NON-REGRESSION: these pass today and must keep passing ---

def test_google_flights_source_satisfies_the_search_source_protocol():
    from backend.sources.base import SearchSource
    from backend.sources.google_flights import GoogleFlightsSource
    assert isinstance(GoogleFlightsSource(), SearchSource)


def test_fast_flights_source_satisfies_the_search_source_protocol():
    from backend.sources.base import SearchSource
    from backend.sources.fast_flights import FastFlightsSource
    assert isinstance(FastFlightsSource(), SearchSource)


def test_fallback_source_satisfies_the_search_source_protocol():
    from backend.sources.base import SearchSource
    from backend.sources.fallback import FallbackSource
    assert isinstance(FallbackSource(), SearchSource)


def test_kayak_source_satisfies_the_search_source_protocol():
    from backend.sources.base import SearchSource
    from backend.sources.kayak import KayakSource
    assert isinstance(KayakSource(), SearchSource)


def test_flight_result_still_carries_its_twelve_fields():
    """FlightResult is deliberately NOT changed by this phase; passenger_count
    arrives in Phase 3."""
    import dataclasses
    from backend.sources.base import FlightResult
    names = {f.name for f in dataclasses.fields(FlightResult)}
    assert names == {
        "source", "price", "currency", "duration_min", "stops", "airline",
        "flight_number", "departure_time", "arrival_time", "legs_json",
        "booking_url",
    }
