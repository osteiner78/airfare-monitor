import pytest


TRACKER_PAYLOAD = {
    "origin": "GVA",
    "destination": "BCN",
    "depart_date": "2026-09-15",
}

NOTIFICATION_PAYLOAD = {
    "rule_type": "price_below",
    "threshold": 150.0,
}


# --- schema ---

async def test_notifications_table_exists_after_init(db_conn):
    async with db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


# --- db CRUD ---

async def test_create_notification_returns_dict_with_id(db_path):
    from backend.db import create_tracker, create_notification
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    notification = await create_notification(
        tracker_id=tracker["id"], rule_type="price_below", threshold=150.0
    )
    assert "id" in notification
    assert isinstance(notification["id"], int)


async def test_list_notifications_returns_empty_for_tracker_with_no_rules(db_path):
    from backend.db import create_tracker, list_notifications
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    result = await list_notifications(tracker["id"])
    assert result == []


async def test_delete_notification_removes_the_row(db_path):
    from backend.db import create_tracker, create_notification, delete_notification, list_notifications
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    notification = await create_notification(
        tracker_id=tracker["id"], rule_type="price_below", threshold=150.0
    )
    await delete_notification(notification["id"])
    result = await list_notifications(tracker["id"])
    assert result == []


# --- API ---

async def test_post_notification_api_returns_201_with_id(client):
    created_tracker = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    payload = {**NOTIFICATION_PAYLOAD, "tracker_id": created_tracker["id"]}
    response = await client.post("/api/notifications", json=payload)
    assert response.status_code == 201
    assert "id" in response.json()


async def test_get_notifications_api_returns_empty_list_for_new_tracker(client):
    created_tracker = (await client.post("/api/trackers", json=TRACKER_PAYLOAD)).json()
    response = await client.get(f"/api/trackers/{created_tracker['id']}/notifications")
    assert response.status_code == 200
    assert response.json() == []


# --- failure modes ---

async def test_delete_notification_api_returns_404_for_unknown_id(client):
    response = await client.delete("/api/notifications/99999")
    assert response.status_code == 404


async def test_post_notification_api_returns_404_for_unknown_tracker_id(client):
    payload = {**NOTIFICATION_PAYLOAD, "tracker_id": 99999}
    response = await client.post("/api/notifications", json=payload)
    assert response.status_code == 404
