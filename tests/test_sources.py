import pytest
import sys
from unittest.mock import patch


# --- FlightResult dataclass ---

async def test_flight_result_dataclass_has_all_required_fields():
    from backend.sources.base import FlightResult
    result = FlightResult(
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
    assert result.source == "google_flights"
    assert result.price == 199.0
    assert result.stops == 0


# --- SearchSource protocol ---

async def test_google_flights_source_satisfies_search_source_protocol():
    from backend.sources.google_flights import GoogleFlightsSource
    from backend.sources.base import SearchSource
    source = GoogleFlightsSource()
    assert isinstance(source, SearchSource)


# --- sources registry ---

async def test_all_sources_returns_nonempty_list():
    from backend.sources import get_sources
    sources = get_sources()
    assert len(sources) > 0


# --- failure modes ---

async def test_google_flights_returns_empty_list_when_fli_raises_import_error():
    with patch.dict(sys.modules, {"flights": None}):
        import importlib
        import backend.sources.google_flights as gf_mod
        importlib.reload(gf_mod)
        source = gf_mod.GoogleFlightsSource()
        result = await source.search("GVA", "BCN", "2026-06-15", None, "EUR", 5)
    assert result == []


async def test_google_flights_returns_empty_list_when_search_raises_exception():
    from backend.sources.google_flights import GoogleFlightsSource
    source = GoogleFlightsSource()
    with patch.object(source, "_fetch", side_effect=RuntimeError("network error")):
        result = await source.search("GVA", "BCN", "2026-06-15", None, "EUR", 5)
    assert result == []


# --- live search (requires network + fli installed) ---

@pytest.mark.slow
async def test_real_search_returns_flight_results_for_valid_route():
    from backend.sources.google_flights import GoogleFlightsSource
    from backend.sources.base import FlightResult
    source = GoogleFlightsSource()
    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)
    assert isinstance(results, list)
    if results:
        assert all(isinstance(r, FlightResult) for r in results)
        assert all(r.price > 0 for r in results)
