import pytest


TRACKER_FORM = {"origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15"}


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_contains_add_form(client):
    response = await client.get("/")
    assert "Add Route" in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_empty_state_when_no_trackers(client):
    response = await client.get("/")
    assert "No trackers yet" in response.text


@pytest.mark.asyncio
async def test_add_tracker_form_returns_200(client):
    response = await client.post("/", data=TRACKER_FORM)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_add_tracker_returns_html_with_route_info(client):
    response = await client.post("/", data=TRACKER_FORM)
    assert "GVA" in response.text
    assert "BCN" in response.text


@pytest.mark.asyncio
async def test_add_tracker_updates_tracker_list(client):
    await client.post("/", data=TRACKER_FORM)
    response = await client.get("/")
    assert "No trackers yet" not in response.text


@pytest.mark.asyncio
async def test_detail_page_returns_200_for_valid_tracker(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.get("/trackers/1")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_detail_page_returns_404_for_missing_tracker(client):
    response = await client.get("/trackers/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_page_contains_tracker_route(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.get("/trackers/1")
    assert "GVA" in response.text
    assert "BCN" in response.text


@pytest.mark.asyncio
async def test_search_now_returns_200(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.post("/trackers/1/search")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_search_now_returns_404_for_missing_tracker(client):
    response = await client.post("/trackers/999/search")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_returns_card_partial(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.patch("/trackers/1/toggle")
    assert response.status_code == 200
    assert "tracker-card" in response.text


@pytest.mark.asyncio
async def test_toggle_returns_404_for_missing_tracker(client):
    response = await client.patch("/trackers/999/toggle")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_page_contains_chart_canvas_when_snapshot_exists(client):
    from backend.db import get_db_path, create_snapshot, insert_flight_prices
    import os
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
    }])
    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "price-chart" in response.text


@pytest.mark.asyncio
async def test_detail_page_contains_results_table_when_snapshot_exists(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "results-table" in response.text


@pytest.mark.asyncio
async def test_detail_page_contains_booking_url_column(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "google.com/travel/flights" in response.text


@pytest.mark.asyncio
async def test_detail_page_does_not_embed_full_html_in_detail_content(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
    }])
    response = await client.post("/trackers/1/search")
    text = response.text
    assert text.count("<html") == 0


# --- Phase 2: results table logo ---

@pytest.mark.asyncio
async def test_results_table_renders_kiwi_logo_for_valid_code(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
        "source": "test",
        "price": 89.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "VY 6201",
        "departure_time": "2026-09-15T10:00:00",
        "arrival_time": "2026-09-15T11:15:00",
        "duration_min": 75,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "images.kiwi.com/airlines/128/VY.png" in response.text


@pytest.mark.asyncio
async def test_results_table_logo_alt_is_airline_name(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
        "source": "test",
        "price": 89.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "VY 6201",
        "departure_time": "2026-09-15T10:00:00",
        "arrival_time": "2026-09-15T11:15:00",
        "duration_min": 75,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'alt="Vueling"' in response.text


@pytest.mark.asyncio
async def test_results_table_falls_back_to_name_when_code_invalid(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "XX" in response.text
    assert "images.kiwi.com" not in response.text


# --- Phase 3: dashboard card logo ---

@pytest.mark.asyncio
async def test_dashboard_card_renders_logo_for_best_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        {
            "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
            "source": "test",
            "price": 150.0,
            "currency": "EUR",
            "airline": "Vueling",
            "flight_number": "VY 6201",
        },
        {
            "flight_key": "test|Lufthansa|LH400|2026-09-15T08:00:00",
            "source": "test",
            "price": 120.0,
            "currency": "EUR",
            "airline": "Lufthansa",
            "flight_number": "LH 400",
        },
    ])
    response = await client.get("/")
    assert "images.kiwi.com/airlines/128/LH.png" in response.text


# --- Plan 009: results-table row colors match chart line colors ---

@pytest.mark.asyncio
async def test_charted_row_carries_its_chart_color(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "--row-color: #4a90d9" in response.text


@pytest.mark.asyncio
async def test_charted_row_has_flight_key_data_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'data-flight-key="test|VY|6201|2026-01-01T00:00:00"' in response.text


@pytest.mark.asyncio
async def test_missing_row_has_no_row_color(client):
    # snapshot 1 has flight A; snapshot 2 replaces it with flight B, so A becomes
    # a "missing" row. Only B is charted, so exactly one row may be colored.
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snap1 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap1["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    snap2 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap2["id"], 1, [{
        "flight_key": "test|LH|400|2026-01-02T00:00:00",
        "source": "test", "price": 120.0, "currency": "EUR",
        "airline": "Lufthansa", "flight_number": "LH 400",
        "departure_time": "2026-01-02T08:00:00",
        "arrival_time": "2026-01-02T10:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'data-flight-key="test|VY|6201|2026-01-01T00:00:00"' in response.text
    assert response.text.count("row-colored") == 1
