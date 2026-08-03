from unittest.mock import AsyncMock


def _flight(price=100.0):
    from backend.sources.base import FlightResult
    return FlightResult(
        source="test", price=price, currency="EUR", duration_min=90, stops=0,
        airline="LX", flight_number="LX 1234",
        departure_time="2026-09-15T07:30:00", arrival_time="2026-09-15T09:00:00",
        legs_json="[]", booking_url="https://example.com",
    )


async def test_fallback_satisfies_search_source_protocol():
    from backend.sources.fallback import FallbackSource
    from backend.sources.base import SearchSource
    assert isinstance(FallbackSource(), SearchSource)


async def test_fallback_returns_primary_results_without_calling_secondary():
    from backend.sources.fallback import FallbackSource
    source = FallbackSource()
    source.primary.search = AsyncMock(return_value=[_flight()])
    source.secondary.search = AsyncMock(return_value=[_flight()])

    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    assert len(results) == 1
    source.secondary.search.assert_not_called()


async def test_fallback_calls_secondary_when_primary_returns_empty():
    from backend.sources.fallback import FallbackSource
    source = FallbackSource()
    source.primary.search = AsyncMock(return_value=[])
    source.primary.last_error = None
    source.primary.last_error_level = "ERROR"
    source.secondary.search = AsyncMock(return_value=[_flight(price=200.0)])

    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    source.secondary.search.assert_called_once()
    assert len(results) == 1
    assert results[0].price == 200.0


async def test_fallback_last_error_combines_both_when_both_empty():
    from backend.sources.fallback import FallbackSource
    source = FallbackSource()
    source.primary.search = AsyncMock(return_value=[])
    source.primary.last_error = "INTERNAL error [13]"
    source.primary.last_error_level = "ERROR"
    source.secondary.search = AsyncMock(return_value=[])
    source.secondary.last_error = "no results found"
    source.secondary.last_error_level = "WARNING"

    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    assert results == []
    assert "INTERNAL error [13]" in source.last_error
    assert "no results found" in source.last_error
    assert source.last_error_level == "ERROR"


async def test_fallback_no_error_when_both_sources_genuinely_empty():
    from backend.sources.fallback import FallbackSource
    source = FallbackSource()
    source.primary.search = AsyncMock(return_value=[])
    source.primary.last_error = None
    source.secondary.search = AsyncMock(return_value=[])
    source.secondary.last_error = None

    results = await source.search("GVA", "BCN", "2026-09-15", None, "EUR", 5)

    assert results == []
    assert source.last_error is None
