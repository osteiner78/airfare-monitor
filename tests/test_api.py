import pytest


TRACKER_PAYLOAD = {
    "origin": "GVA",
    "destination": "BCN",
    "depart_date": "2026-09-15",
}


# --- list trackers ---

async def test_get_trackers_returns_empty_list_initially(client):
    response = await client.get("/api/trackers")
    assert response.status_code == 200
    assert response.json() == []


# --- create tracker ---

async def test_post_trackers_returns_201_with_tracker_id(client):
    response = await client.post("/api/trackers", json=TRACKER_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert isinstance(data["id"], int)


async def test_post_trackers_adds_tracker_visible_in_list(client):
    await client.post("/api/trackers", json=TRACKER_PAYLOAD)
    response = await client.get("/api/trackers")
    assert len(response.json()) == 1


# --- get single tracker ---

async def test_get_tracker_by_id_returns_tracker(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.get(f"/api/trackers/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_tracker_returns_404_for_unknown_id(client):
    response = await client.get("/api/trackers/99999")
    assert response.status_code == 404


# --- patch tracker ---

async def test_patch_tracker_sets_active_to_false(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.patch(f"/api/trackers/{created['id']}", json={"active": False})
    assert response.status_code == 200
    assert response.json()["active"] is False


# --- delete tracker ---

async def test_delete_tracker_returns_204(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.delete(f"/api/trackers/{created['id']}")
    assert response.status_code == 204


async def test_delete_tracker_removes_tracker_from_list(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    await client.delete(f"/api/trackers/{created['id']}")
    response = await client.get("/api/trackers")
    assert response.json() == []


async def test_delete_tracker_returns_404_for_unknown_id(client):
    response = await client.delete("/api/trackers/99999")
    assert response.status_code == 404


# --- history ---

async def test_get_history_returns_empty_flights_for_new_tracker(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.get(f"/api/trackers/{created['id']}/history")
    assert response.status_code == 200
    data = response.json()
    assert "flights" in data
    assert data["flights"] == []


# --- manual search ---

async def test_post_search_returns_200(client):
    created = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.post(f"/api/trackers/{created['id']}/search")
    assert response.status_code == 200


# --- validation failure modes ---

async def test_post_trackers_returns_422_when_origin_is_missing(client):
    response = await client.post("/api/trackers", json={"destination": "BCN", "depart_date": "2026-09-15"})
    assert response.status_code == 422


async def test_post_trackers_returns_422_when_destination_is_missing(client):
    response = await client.post("/api/trackers", json={"origin": "GVA", "depart_date": "2026-09-15"})
    assert response.status_code == 422


async def test_post_trackers_returns_422_when_depart_date_is_missing(client):
    response = await client.post("/api/trackers", json={"origin": "GVA", "destination": "BCN"})
    assert response.status_code == 422


async def test_post_trackers_returns_422_when_depart_date_format_is_invalid(client):
    response = await client.post(
        "/api/trackers", json={"origin": "GVA", "destination": "BCN", "depart_date": "15-06-2026"}
    )
    assert response.status_code == 422
