import pytest
from backend.models import TrackerCreate


@pytest.mark.asyncio
async def test_origin_is_uppercased_on_create():
    tracker = TrackerCreate(origin="gva", destination="BCN", depart_date="2026-09-15")
    assert tracker.origin == "GVA"


@pytest.mark.asyncio
async def test_destination_is_uppercased_on_create():
    tracker = TrackerCreate(origin="GVA", destination="bcn", depart_date="2026-09-15")
    assert tracker.destination == "BCN"


@pytest.mark.asyncio
async def test_origin_preserves_uppercase():
    tracker = TrackerCreate(origin="GVA", destination="BCN", depart_date="2026-09-15")
    assert tracker.origin == "GVA"


@pytest.mark.asyncio
async def test_depart_date_validation_still_works():
    with pytest.raises(Exception):
        TrackerCreate(origin="GVA", destination="BCN", depart_date="not-a-date")


@pytest.mark.asyncio
async def test_case_insensitive_airport_codes_are_normalized():
    tracker = TrackerCreate(origin="Cdg", destination="LhR", depart_date="2026-09-15")
    assert tracker.origin == "CDG"
    assert tracker.destination == "LHR"


@pytest.mark.asyncio
async def test_api_create_tracker_uppercases_codes(client):
    response = await client.post("/api/trackers", json={
        "origin": "gva",
        "destination": "bcn",
        "depart_date": "2026-09-15",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["origin"] == "GVA"
    assert data["destination"] == "BCN"
