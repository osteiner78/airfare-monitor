import pytest


@pytest.mark.asyncio
async def test_notification_log_table_exists_after_init(db_path):
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notification_log'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_insert_notification_log_returns_dict_with_id(db_path):
    from backend.db import create_notification, create_tracker, insert_notification_log
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    notification = await create_notification(tracker["id"], "price_below", 200.0)
    result = await insert_notification_log(notification["id"], tracker["id"], 150.0)
    assert "id" in result
    assert result["tracker_id"] == tracker["id"]
    assert result["best_price"] == 150.0


@pytest.mark.asyncio
async def test_get_recent_alerts_returns_zero_for_tracker_with_no_alerts(db_path):
    from backend.db import create_tracker, get_recent_alerts_count
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    count = await get_recent_alerts_count(tracker["id"])
    assert count == 0


@pytest.mark.asyncio
async def test_notification_log_columns_match_schema(db_path):
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='notification_log'"
        )
        row = await cursor.fetchone()
    assert row is not None
    assert "triggered_at" in row[0]
    assert "notification_id" in row[0]
    assert "best_price" in row[0]
