"""Two sources quoting the exact same physical flight at the exact same
price is pure clutter, not information -- the flight_key already says
they're the same flight, and an identical price says there's nothing to
compare. Rows sharing a flight_key at DIFFERENT prices stay split: that
disagreement is the whole point of tracking more than one source.
"""

import pytest

TRACKER = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}

SHARED_KEY = "iberia|2026-08-21T19:20:00|2026-08-22T19:40:00"


def _row(source, price, **over):
    row = {
        "flight_key": SHARED_KEY, "source": source, "price": price,
        "currency": "EUR", "airline": "Iberia", "flight_number": "",
        "departure_time": "2026-08-21T19:20:00",
        "arrival_time": "2026-08-22T19:40:00",
        "duration_min": 1160, "stops": 1,
    }
    row.update(over)
    return row


async def _search(client, rows):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER)
    snapshot = await create_snapshot(1, results_count=len(rows))
    await insert_flight_prices(snapshot["id"], 1, rows)
    return await client.get("/trackers/1")


@pytest.mark.asyncio
async def test_identical_price_across_sources_collapses_to_one_row(client):
    page = (await _search(client, [
        _row("google_flights", 711.0, flight_number="IB 272+IB 1287"),
        _row("kayak", 711.0),
    ])).text
    assert page.count(f'data-flight-key="{SHARED_KEY}"') == 1


@pytest.mark.asyncio
async def test_collapsed_row_lists_every_source(client):
    page = (await _search(client, [
        _row("google_flights", 711.0, flight_number="IB 272+IB 1287"),
        _row("kayak", 711.0),
    ])).text
    assert "Google Flights, Kayak" in page


@pytest.mark.asyncio
async def test_collapsed_row_keeps_the_non_empty_flight_number(client):
    """Kayak's collapsed view never prints a flight number; a duplicate
    Google row shouldn't lose its more informative one on merge."""
    page = (await _search(client, [
        _row("kayak", 711.0),
        _row("google_flights", 711.0, flight_number="IB 272+IB 1287"),
    ])).text
    assert "IB 272+IB 1287" in page


@pytest.mark.asyncio
async def test_differing_price_across_sources_stays_split(client):
    """The case the design exists for: Kayak and Google disagree, and both
    quotes should stay visible so the user can compare."""
    page = (await _search(client, [
        _row("kayak", 796.0, airline="TAP AIR PORTUGAL"),
        _row("google_flights", 812.0, airline="TAP AIR PORTUGAL", flight_number="TP 88+TP 932"),
    ])).text
    assert page.count(f'data-flight-key="{SHARED_KEY}"') == 2
    assert "€796" in page
    assert "€812" in page
