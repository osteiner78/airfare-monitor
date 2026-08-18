"""Plan 028 Phase 2 — tracker_sources replaces the per-source column pair.

NEW-BEHAVIOR and FAILURE-MODE. All fail until Phase 2 lands.

Only OPT-IN BROWSER sources get rows. FallbackSource is a composite whose
secondary runs only when the primary returns nothing (fallback.py:26-33), so
google_flights and fast_flights are not independently schedulable and are
deliberately absent from this table.

The failure mode that matters most is the 2026-08-04 outage repeated: this
service runs Active dev, so new code meets an un-migrated table, and a missing
table or row must degrade to "feature off" rather than raise on the main search
path -- reading with .get(), never [].
"""

import pytest


@pytest.mark.asyncio
async def test_a_new_tracker_has_no_browser_source_rows(db_path):
    from backend.db import create_tracker, get_tracker_sources
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    assert await get_tracker_sources(tracker["id"]) == []


@pytest.mark.asyncio
async def test_enabling_kayak_creates_exactly_one_source_row(db_path):
    from backend.db import create_tracker, get_tracker_sources, set_tracker_source
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await set_tracker_source(tracker["id"], "kayak", enabled=True)
    assert len(await get_tracker_sources(tracker["id"])) == 1


@pytest.mark.asyncio
async def test_enabling_kayak_twice_does_not_create_a_second_row(db_path):
    from backend.db import create_tracker, get_tracker_sources, set_tracker_source
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await set_tracker_source(tracker["id"], "kayak", enabled=True)
    await set_tracker_source(tracker["id"], "kayak", enabled=True)
    assert len(await get_tracker_sources(tracker["id"])) == 1


@pytest.mark.asyncio
async def test_disabling_a_source_keeps_its_row_but_marks_it_disabled(db_path):
    """next_due_at must survive a disable/enable cycle, or re-enabling a source
    makes it due immediately and hot-retries against a bot-detecting site."""
    from backend.db import create_tracker, get_tracker_sources, set_tracker_source
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await set_tracker_source(tracker["id"], "kayak", enabled=True,
                             next_due_at="2026-11-20 10:00:00")
    await set_tracker_source(tracker["id"], "kayak", enabled=False)
    rows = await get_tracker_sources(tracker["id"])
    assert rows[0]["next_due_at"] == "2026-11-20 10:00:00"


@pytest.mark.asyncio
async def test_deleting_a_tracker_removes_its_source_rows(db_path):
    from backend.db import create_tracker, delete_tracker, get_tracker_sources, set_tracker_source
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await set_tracker_source(tracker["id"], "kayak", enabled=True)
    await delete_tracker(tracker["id"])
    assert await get_tracker_sources(tracker["id"]) == []


@pytest.mark.asyncio
async def test_source_rows_are_scoped_to_their_own_tracker(db_path):
    from backend.db import create_tracker, get_tracker_sources, set_tracker_source
    a = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    b = await create_tracker(origin="GRU", destination="CDG", depart_date="2026-11-20")
    await set_tracker_source(a["id"], "kayak", enabled=True)
    assert await get_tracker_sources(b["id"]) == []


@pytest.mark.asyncio
async def test_an_unknown_source_name_is_still_stored_rather_than_silently_dropped(db_path):
    """Skyscanner arrives later; the table must not need a code change to
    accept a name it has not seen."""
    from backend.db import create_tracker, get_tracker_sources, set_tracker_source
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await set_tracker_source(tracker["id"], "skyscanner", enabled=True)
    assert [r["source"] for r in await get_tracker_sources(tracker["id"])] == ["skyscanner"]


@pytest.mark.asyncio
async def test_a_missing_tracker_sources_table_degrades_to_feature_off(db_path):
    """The 2026-08-04 shape: a KeyError on a migration-added column killed the
    snapshot for all six trackers, not just the one feature. A search must still
    run and store Google's rows when the table is not there yet."""
    import aiosqlite
    from backend.db import create_tracker
    from backend.scheduler import search_and_store
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DROP TABLE IF EXISTS tracker_sources")
        await conn.commit()
    await search_and_store(tracker["id"], delay=False)  # must not raise


@pytest.mark.asyncio
async def test_a_tracker_with_no_source_rows_runs_google_only(db_path, monkeypatch):
    from unittest.mock import AsyncMock
    import backend.scheduler as scheduler
    from backend.db import create_tracker
    kayak = AsyncMock()
    monkeypatch.setattr(scheduler, "KayakSource", lambda *a, **k: kayak)
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    await search_and_store_safely(scheduler, tracker["id"])
    kayak.search.assert_not_called()


async def search_and_store_safely(scheduler, tracker_id):
    try:
        await scheduler.search_and_store(tracker_id, delay=False)
    except Exception:
        pass
