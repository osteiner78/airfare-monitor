"""Tests for plan 010 — tracker-page filter sidebar (stops + duration).

Automated coverage targets the SERVER side only: the data contract shipped to the
browser (`window.allFlights`), the per-row filter attributes, and the server-rendered
sidebar controls. The client-side filtering BEHAVIOUR (greying rows, recomputing the
chart) has no automated coverage — this repo is pytest-only with no JS test runner —
and is verified via the manual smoke matrix in .agent/reports/010-phase-4.md.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.
  NON-REGRESSION               -> must already pass against current code.
"""

import json
import re

import pytest


def _extract_js_global(text: str, name: str):
    """Pull `window.<name> = <json>;</script>` out of a rendered page and parse it.
    Returns None when the global is absent, so fail-first tests fail on a real
    assertion rather than a regex/JSON crash."""
    match = re.search(r"window\." + re.escape(name) + r" = (.*?);</script>", text, re.DOTALL)
    if match is None:
        return None
    return json.loads(match.group(1))


async def _make_tracker(client):
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })


def _price(flight_key, price, **over):
    base = {
        "flight_key": flight_key, "source": "test", "price": float(price), "currency": "EUR",
        "airline": "Test", "flight_number": flight_key.split("|")[2],
        "departure_time": "2026-01-01T08:00:00", "arrival_time": "2026-01-01T10:00:00",
        "duration_min": 120, "stops": 0,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Phase 2 — data contract: window.allFlights + per-row attributes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_flights_includes_flight_beyond_top_n(client):
    # top_n default is 5: insert 6 flights at distinct prices. The chart is capped at
    # 5, but allFlights must carry all 6 so a filter can promote the 6th. (off-by-one)
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=6)
    prices = [_price(f"test|XX|{i}|2026-01-01T00:00:00", (i + 1) * 10) for i in range(6)]
    await insert_flight_prices(snap["id"], 1, prices)

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    keys = {f["flight_key"] for f in all_flights}
    assert "test|XX|5|2026-01-01T00:00:00" in keys


@pytest.mark.asyncio
async def test_chart_data_capped_at_top_n_while_all_flights_is_not(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=6)
    prices = [_price(f"test|XX|{i}|2026-01-01T00:00:00", (i + 1) * 10) for i in range(6)]
    await insert_flight_prices(snap["id"], 1, prices)

    response = await client.get("/trackers/1")
    chart = _extract_js_global(response.text, "chartData")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    assert len(chart) == 5
    assert len(all_flights) == 6


@pytest.mark.asyncio
async def test_all_flights_entry_includes_stops_and_duration(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, stops=1, duration_min=345),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    entry = all_flights[0]
    assert entry["stops"] == 1
    assert entry["duration_min"] == 345


@pytest.mark.asyncio
async def test_all_flights_includes_full_history_series_per_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap1 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap1["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])
    snap2 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap2["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 80),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    entry = next(f for f in all_flights if f["flight_key"] == "test|VY|6201|2026-01-01T00:00:00")
    assert len(entry["data"]) == 2


@pytest.mark.asyncio
async def test_row_carries_data_stops_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, stops=0),
    ])

    response = await client.get("/trackers/1")
    assert 'data-stops="0"' in response.text


@pytest.mark.asyncio
async def test_row_carries_data_duration_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=120),
    ])

    response = await client.get("/trackers/1")
    assert 'data-duration="120"' in response.text


@pytest.mark.asyncio
async def test_all_flights_is_empty_array_when_no_snapshot(client):
    # FAILURE-MODE: tracker exists but never searched -> allFlights must be [].
    await _make_tracker(client)
    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights == []


@pytest.mark.asyncio
async def test_row_with_null_duration_renders_empty_data_duration(client):
    # FAILURE-MODE: a flight with unknown duration must render data-duration="" and
    # not crash template rendering.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=None),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'data-duration=""' in response.text


# ---------------------------------------------------------------------------
# Phase 4 — server-rendered sidebar controls (bounds derived from data)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_page_renders_filter_sidebar(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])

    response = await client.get("/trackers/1")
    assert "filter-sidebar" in response.text


@pytest.mark.asyncio
async def test_duration_slider_max_equals_longest_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, duration_min=120),
        _price("test|VY|2|2026-01-01T00:00:00", 110, duration_min=540),
    ])

    response = await client.get("/trackers/1")
    assert 'id="filter-duration"' in response.text
    assert 'max="540"' in response.text


@pytest.mark.asyncio
async def test_stops_select_max_option_equals_most_stops(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=3)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, stops=0),
        _price("test|VY|2|2026-01-01T00:00:00", 110, stops=1),
        _price("test|VY|3|2026-01-01T00:00:00", 120, stops=2),
    ])

    response = await client.get("/trackers/1")
    assert 'id="filter-stops"' in response.text
    assert '<option value="2"' in response.text


@pytest.mark.asyncio
async def test_sidebar_renders_with_single_flight(client):
    # EDGE: single flight -> sidebar still renders.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])

    response = await client.get("/trackers/1")
    assert "filter-sidebar" in response.text


@pytest.mark.asyncio
async def test_duration_slider_max_is_zero_when_all_durations_null(client):
    # EDGE: every flight has unknown duration -> slider max collapses to 0, no crash.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=None),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'id="filter-duration"' in response.text
    assert 'max="0"' in response.text
