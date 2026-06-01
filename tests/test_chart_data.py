import pytest


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n(db_path):
    from backend.db import create_snapshot, create_tracker, get_sticky_top_flight_keys, insert_flight_prices

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=3)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "test|VY|6201|2026-01-01T00:00:00", "source": "test", "price": 33.0, "currency": "EUR"},
        {"flight_key": "test|U2|7108|2026-01-01T00:00:00", "source": "test", "price": 45.0, "currency": "EUR"},
        {"flight_key": "test|LH|1234|2026-01-01T00:00:00", "source": "test", "price": 100.0, "currency": "EUR"},
    ])

    keys = await get_sticky_top_flight_keys(tracker["id"], 2)
    assert len(keys) == 2
    assert "test|VY|6201|2026-01-01T00:00:00" in keys
    assert "test|U2|7108|2026-01-01T00:00:00" in keys


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots(db_path):
    from backend.db import create_tracker, get_sticky_top_flight_keys

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    keys = await get_sticky_top_flight_keys(tracker["id"], 5)
    assert keys == set() or len(keys) == 0


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker(db_path):
    from backend.db import get_sticky_top_flight_keys

    keys = await get_sticky_top_flight_keys(999, 5)
    assert keys == set() or len(keys) == 0


@pytest.mark.asyncio
async def test_chart_datasets_limited_to_sticky_top_n(client):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert '"label": "6201"' in response.text


# --- NEW-BEHAVIOR (plan 009): chart datasets carry a server-assigned color ---

@pytest.mark.asyncio
async def test_chart_dataset_includes_color_field(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert '"color"' in response.text


@pytest.mark.asyncio
async def test_chart_dataset_color_is_first_palette_color_for_single_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "#4a90d9" in response.text
