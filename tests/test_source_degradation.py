"""Two silent-degradation defects found on live data 2026-08-11.

1. UNIDENTIFIABLE fast_flights ROWS. `_to_iso` deliberately returns "" when
   Google hands back a null date component (better than fabricating midnight,
   better than raising and killing the whole fetch). That was safe while
   `flight_key` still carried `flight_number` -- plan 019 removed it, leaving
   `airline|departure|arrival`, so an empty component produces
   `tap air portugal||2026-08-21T22:30:00`. Every flight by that airline
   arriving at that time collapses into one identity. 96 such rows reached
   production before anyone noticed.

2. SILENT FALLBACK. `FallbackSource` returned the secondary source's rows
   without recording anything, so fli failing looked identical to fli
   succeeding. Observed: fli 113 rows cheapest EUR784 -> fast_flights 6 rows
   cheapest EUR957, headline price jumped ~EUR170, `system_logs` empty. The
   scheduler only writes a log line when `last_error` is set, so staying
   silent here meant the degradation was invisible on /monitor.
"""

import pytest

from backend.fingerprint import make_flight_key
from backend.sources.base import FlightResult


def _row(**kw):
    base = dict(
        source="fast_flights", price=100.0, currency="EUR", duration_min=600,
        stops=1, airline="TAP AIR PORTUGAL", flight_number="TP 1",
        departure_time="2026-08-21T20:45:00", arrival_time="2026-08-22T17:15:00",
        legs_json="[]", booking_url="",
    )
    base.update(kw)
    return FlightResult(**base)


# --- 1. unidentifiable rows ---

def test_an_empty_departure_time_collides_with_other_flights():
    """Why the row has to go: two genuinely different itineraries produce one
    identical key once the departure component is empty."""
    a = _row(departure_time="", arrival_time="2026-08-21T22:30:00", flight_number="TP 1")
    b = _row(departure_time="", arrival_time="2026-08-21T22:30:00", flight_number="TP 99")
    assert make_flight_key(a) == make_flight_key(b), (
        "premise of this test no longer holds -- if the key disambiguates "
        "these, dropping the rows may no longer be necessary"
    )


class _FakeParsed:
    def __init__(self, price):
        self.price = price
        self.airlines = ["TAP AIR PORTUGAL"]
        self.flights = []


async def _fetch_with(monkeypatch, mapped_rows):
    """Drive FastFlightsSource._fetch with no network.

    `_fetch` imports `fast_flights` *inside the function*, so the stub has to
    be installed in sys.modules -- patching the attribute on our own module
    does nothing.
    """
    import sys
    import types

    from backend.sources.fast_flights import FastFlightsSource

    source = FastFlightsSource()
    rows = iter(mapped_rows)
    monkeypatch.setattr(FastFlightsSource, "_map_result",
                        lambda self, r, n, c, q: next(rows))
    monkeypatch.setattr(FastFlightsSource, "_extract_flight_numbers",
                        staticmethod(lambda html: []))

    class _Query:
        def url(self):
            return ""

    parser_mod = types.SimpleNamespace(parse=lambda html: [_FakeParsed(100.0) for _ in mapped_rows])
    fake = types.SimpleNamespace(
        create_query=lambda **kw: _Query(),
        fetch_flights_html=lambda query: "<html></html>",
        FlightQuery=lambda **kw: None,
        parser=parser_mod,
    )
    exceptions_mod = types.SimpleNamespace(FlightsNotFound=type("FlightsNotFound", (Exception,), {}))

    monkeypatch.setitem(sys.modules, "fast_flights", fake)
    monkeypatch.setitem(sys.modules, "fast_flights.exceptions", exceptions_mod)
    return source


@pytest.mark.asyncio
async def test_rows_without_a_departure_time_are_dropped(monkeypatch):
    source = await _fetch_with(monkeypatch, [
        _row(),
        _row(departure_time="", arrival_time="2026-08-21T22:30:00"),
    ])
    out = await source._fetch("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert len(out) == 1
    assert all(r.departure_time and r.arrival_time for r in out)


@pytest.mark.asyncio
async def test_dropping_rows_is_reported_so_it_reaches_system_logs(monkeypatch):
    """logger.warning does not reach the system_logs table -- nothing in this
    project configures a handler that writes there. last_error is the channel
    the scheduler actually reads."""
    source = await _fetch_with(monkeypatch, [
        _row(),
        _row(departure_time=""),
    ])
    await source._fetch("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert source.last_error is not None
    assert "1" in source.last_error
    assert source.last_error_level == "WARNING"


@pytest.mark.asyncio
async def test_a_clean_fetch_reports_nothing(monkeypatch):
    source = await _fetch_with(monkeypatch, [_row(), _row(price=200.0)])
    out = await source._fetch("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert len(out) == 2
    assert source.last_error is None


# --- 2. the silent fallback ---

class _StubSource:
    def __init__(self, rows, error=None, level="ERROR"):
        self._rows = rows
        self.last_error = error
        self.last_error_level = level

    async def search(self, *a, **kw):
        return list(self._rows)


@pytest.mark.asyncio
async def test_falling_back_to_the_secondary_is_recorded():
    from backend.sources.fallback import FallbackSource

    source = FallbackSource()
    source.primary = _StubSource([])
    source.secondary = _StubSource([_row(price=957.0)])

    results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert len(results) == 1, "the fallback's rows must still be returned"
    assert source.last_error is not None, "fli failing was invisible on /monitor"
    assert "fast_flights" in source.last_error
    assert source.last_error_level == "WARNING", "degraded but still serving prices"


@pytest.mark.asyncio
async def test_a_healthy_primary_reports_nothing():
    from backend.sources.fallback import FallbackSource

    source = FallbackSource()
    source.primary = _StubSource([_row(price=784.0)])
    source.secondary = _StubSource([_row(price=957.0)])

    results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results[0].price == 784.0
    assert source.last_error is None, "a normal cycle must not warn"


@pytest.mark.asyncio
async def test_the_primarys_own_error_survives_into_the_fallback_message():
    from backend.sources.fallback import FallbackSource

    source = FallbackSource()
    source.primary = _StubSource([], error="RateLimited: 429")
    source.secondary = _StubSource([_row(price=957.0)])

    await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert "RateLimited: 429" in source.last_error
