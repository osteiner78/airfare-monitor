import pytest


@pytest.mark.asyncio
async def test_insert_log_returns_dict_with_id(db_path):
    from backend.db import insert_log

    result = await insert_log("INFO", "search_done", tracker_id=1, message="151 results")
    assert "id" in result
    assert result["level"] == "INFO"
    assert result["event"] == "search_done"


@pytest.mark.asyncio
async def test_get_recent_logs_returns_newest_first(db_path):
    from backend.db import get_recent_logs, insert_log

    await insert_log("INFO", "first", tracker_id=None, message="old")
    await insert_log("INFO", "second", tracker_id=None, message="new")

    logs = await get_recent_logs(limit=50)
    assert len(logs) >= 2
    assert logs[0]["event"] == "second"
    assert logs[1]["event"] == "first"


@pytest.mark.asyncio
async def test_get_recent_logs_respects_limit(db_path):
    from backend.db import get_recent_logs, insert_log

    for i in range(5):
        await insert_log("INFO", f"event_{i}", tracker_id=None, message=f"msg {i}")

    logs = await get_recent_logs(limit=2)
    assert len(logs) == 2


@pytest.mark.asyncio
async def test_monitor_page_returns_200(client):
    response = await client.get("/monitor")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tracker_creation_creates_log_entry(client):
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    from backend.db import get_recent_logs
    logs = await get_recent_logs(limit=10)
    events = [log["event"] for log in logs]
    assert "tracker_created" in events


@pytest.mark.asyncio
async def test_insert_log_with_null_tracker_id(db_path):
    from backend.db import insert_log, get_recent_logs

    await insert_log("ERROR", "server_error", tracker_id=None, message="something broke")
    logs = await get_recent_logs(limit=1)
    assert logs[0]["tracker_id"] is None
    assert logs[0]["level"] == "ERROR"
