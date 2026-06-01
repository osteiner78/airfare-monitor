import pytest
import aiosqlite


# --- schema / init ---

async def test_wal_mode_enabled_after_init(db_conn):
    async with db_conn.execute("PRAGMA journal_mode") as cur:
        row = await cur.fetchone()
    assert row[0] == "wal"


async def test_trackers_table_exists_after_init(db_conn):
    async with db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trackers'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_snapshots_table_exists_after_init(db_conn):
    async with db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_flight_prices_table_exists_after_init(db_conn):
    async with db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='flight_prices'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


# --- tracker CRUD ---

async def test_create_tracker_returns_dict_with_id(db_path):
    from backend.db import create_tracker
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    assert "id" in tracker
    assert isinstance(tracker["id"], int)
    assert tracker["id"] > 0


async def test_create_tracker_stores_all_provided_fields(db_path):
    from backend.db import create_tracker
    tracker = await create_tracker(
        origin="GVA", destination="BCN", depart_date="2026-06-15", currency="CHF"
    )
    assert tracker["origin"] == "GVA"
    assert tracker["destination"] == "BCN"
    assert tracker["depart_date"] == "2026-06-15"
    assert tracker["currency"] == "CHF"


async def test_list_trackers_returns_empty_list_when_no_trackers_exist(db_path):
    from backend.db import list_trackers
    result = await list_trackers()
    assert result == []


async def test_get_tracker_returns_tracker_by_id(db_path):
    from backend.db import create_tracker, get_tracker
    created = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    fetched = await get_tracker(created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["origin"] == "GVA"


async def test_update_tracker_sets_active_to_false(db_path):
    from backend.db import create_tracker, update_tracker, get_tracker
    created = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    await update_tracker(created["id"], active=False)
    fetched = await get_tracker(created["id"])
    assert fetched["active"] is False or fetched["active"] == 0


async def test_delete_tracker_removes_the_row(db_path):
    from backend.db import create_tracker, delete_tracker, get_tracker
    created = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    await delete_tracker(created["id"])
    assert await get_tracker(created["id"]) is None


async def test_delete_tracker_cascades_to_snapshots(db_path, db_conn):
    from backend.db import create_tracker, delete_tracker, create_snapshot
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    await create_snapshot(tracker["id"], results_count=0)
    await delete_tracker(tracker["id"])
    async with db_conn.execute(
        "SELECT id FROM snapshots WHERE tracker_id = ?", (tracker["id"],)
    ) as cur:
        rows = await cur.fetchall()
    assert rows == []


# --- snapshots ---

async def test_create_snapshot_returns_dict_with_id(db_path):
    from backend.db import create_tracker, create_snapshot
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    snapshot = await create_snapshot(tracker["id"], results_count=3)
    assert "id" in snapshot
    assert isinstance(snapshot["id"], int)
    assert snapshot["id"] > 0


# --- history / summaries ---

async def test_get_price_history_returns_empty_for_tracker_with_no_snapshots(db_path):
    from backend.db import create_tracker, get_price_history
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-06-15")
    history = await get_price_history(tracker["id"])
    assert history == [] or history == {}


async def test_get_tracker_summaries_returns_empty_list_when_no_trackers(db_path):
    from backend.db import get_tracker_summaries
    result = await get_tracker_summaries()
    assert result == []


# --- failure modes ---

async def test_get_tracker_returns_none_when_id_does_not_exist(db_path):
    from backend.db import get_tracker
    result = await get_tracker(99999)
    assert result is None


async def test_get_tracker_returns_none_for_zero_id(db_path):
    from backend.db import get_tracker
    result = await get_tracker(0)
    assert result is None


async def test_get_tracker_returns_none_for_negative_id(db_path):
    from backend.db import get_tracker
    result = await get_tracker(-1)
    assert result is None


async def test_delete_tracker_on_missing_id_does_not_raise(db_path):
    from backend.db import delete_tracker
    await delete_tracker(99999)


# --- Phase 3: best_flight_number in summaries ---

async def test_summary_includes_best_flight_number_of_cheapest_flight(db_path):
    from backend.db import create_tracker, create_snapshot, insert_flight_prices, get_tracker_summaries
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {
            "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
            "source": "test",
            "price": 200.0,
            "currency": "EUR",
            "flight_number": "VY 6201",
        },
        {
            "flight_key": "test|Lufthansa|LH400|2026-09-15T08:00:00",
            "source": "test",
            "price": 100.0,
            "currency": "EUR",
            "flight_number": "LH 400",
        },
    ])
    summaries = await get_tracker_summaries()
    assert len(summaries) == 1
    assert summaries[0]["best_flight_number"] == "LH 400"


async def test_summary_best_flight_number_is_none_without_snapshot(db_path):
    from backend.db import create_tracker, get_tracker_summaries
    await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    summaries = await get_tracker_summaries()
    assert len(summaries) == 1
    assert summaries[0]["best_flight_number"] is None


async def test_summary_still_returns_min_best_price(db_path):
    from backend.db import create_tracker, create_snapshot, insert_flight_prices, get_tracker_summaries
    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {
            "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
            "source": "test",
            "price": 200.0,
            "currency": "EUR",
            "flight_number": "VY 6201",
        },
        {
            "flight_key": "test|Lufthansa|LH400|2026-09-15T08:00:00",
            "source": "test",
            "price": 100.0,
            "currency": "EUR",
            "flight_number": "LH 400",
        },
    ])
    summaries = await get_tracker_summaries()
    assert summaries[0]["best_price"] == 100.0
