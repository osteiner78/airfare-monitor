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
