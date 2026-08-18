"""Plan 028 Phase 6 — run-length compress the price series.

NEW-BEHAVIOR and FAILURE-MODE. All fail until Phase 6 lands.

Measured 2026-08-15: 141,910 of 276,493 rows (51.3%) are interior points of a
run where a flight held the same price in both the previous and the next
observation.

The trap this phase exists to avoid: THIS APP READS A ROW'S ABSENCE FROM A
SNAPSHOT AS A FACT. Absence means "this flight is no longer offered" -- it
drives the `missing` delta and the blended per-source reconstruction (see
"Sources are BLENDED per source" in CLAUDE.md). Delete an unchanged row and
absence becomes ambiguous. So runs are made EXPLICIT via observed_until;
nothing is ever silently removed.

test_a_flight_that_actually_disappears_is_still_reported_missing is the one that
matters most: it is the assertion that distinguishes "unchanged" from "gone",
and if it cannot be kept green, the design is wrong -- stop and re-plan rather
than adjust the test.
"""

import pytest


@pytest.mark.asyncio
async def test_a_flat_price_run_stores_endpoints_not_every_observation(db_path, db_conn):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for _ in range(5):
        snapshot = await create_snapshot(tracker["id"], results_count=1)
        await insert_flight_prices(snapshot["id"], tracker["id"], [{
            "flight_key": key, "source": "google_flights", "price": 500.0,
            "currency": "EUR",
        }])
    async with db_conn.execute(
        "SELECT count(*) FROM flight_prices WHERE flight_key = ?", (key,)
    ) as cur:
        assert (await cur.fetchone())[0] == 2


@pytest.mark.asyncio
async def test_a_price_change_starts_a_new_run(db_path, db_conn):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for price in (500.0, 500.0, 620.0):
        snapshot = await create_snapshot(tracker["id"], results_count=1)
        await insert_flight_prices(snapshot["id"], tracker["id"], [{
            "flight_key": key, "source": "google_flights", "price": price,
            "currency": "EUR",
        }])
    async with db_conn.execute(
        "SELECT count(DISTINCT price) FROM flight_prices WHERE flight_key = ?", (key,)
    ) as cur:
        assert (await cur.fetchone())[0] == 2


@pytest.mark.asyncio
async def test_expanding_a_run_reproduces_the_original_chart_points(db_path):
    """The chart must look identical to today's. A run is a storage detail, not
    a change to what was observed."""
    from backend.db import create_snapshot, create_tracker, get_price_history, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for _ in range(4):
        snapshot = await create_snapshot(tracker["id"], results_count=1)
        await insert_flight_prices(snapshot["id"], tracker["id"], [{
            "flight_key": key, "source": "google_flights", "price": 500.0,
            "currency": "EUR",
        }])
    history = await get_price_history(tracker["id"])
    assert len([p for p in history if p["flight_key"] == key]) == 4


@pytest.mark.asyncio
async def test_a_flight_inside_a_run_is_not_reported_missing(db_path, client):
    """An unchanged price is presence, not absence."""
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for _ in range(3):
        snapshot = await create_snapshot(tracker["id"], results_count=1)
        await insert_flight_prices(snapshot["id"], tracker["id"], [{
            "flight_key": key, "source": "google_flights", "price": 500.0,
            "currency": "EUR", "airline": "Iberia",
        }])
    page = (await client.get(f"/trackers/{tracker['id']}")).text
    assert "missing" not in page.lower()


@pytest.mark.asyncio
async def test_a_flight_that_actually_disappears_is_still_reported_missing(db_path):
    """The assertion that separates 'unchanged' from 'gone'. If this cannot be
    kept green, the run design is wrong -- re-plan, do not weaken this."""
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    gone = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    stays = "lh|2026-11-20T08:00:00|2026-11-20T22:00:00"
    first = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(first["id"], tracker["id"], [
        {"flight_key": gone, "source": "google_flights", "price": 500.0, "currency": "EUR"},
        {"flight_key": stays, "source": "google_flights", "price": 600.0, "currency": "EUR"},
    ])
    second = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(second["id"], tracker["id"], [
        {"flight_key": stays, "source": "google_flights", "price": 600.0, "currency": "EUR"},
    ])
    keys = {r["flight_key"] for r in await get_flight_prices_for_snapshot(second["id"])}
    assert gone not in keys


@pytest.mark.asyncio
async def test_historical_best_price_is_unchanged_by_compression(db_path):
    """MIN over a flat run is preserved by its endpoints -- but assert it,
    because historical_best_price is never recomputed and a mistake here is
    permanent."""
    from backend.db import create_snapshot, create_tracker, get_historical_best_price, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for price in (700.0, 654.0, 654.0, 654.0, 800.0):
        snapshot = await create_snapshot(tracker["id"], results_count=1)
        await insert_flight_prices(snapshot["id"], tracker["id"], [{
            "flight_key": key, "source": "google_flights", "price": price,
            "currency": "EUR",
        }])
    assert await get_historical_best_price(tracker["id"]) == 654.0


@pytest.mark.asyncio
async def test_a_single_observation_is_its_own_complete_run(db_path, db_conn):
    """Off-by-one: a run of length 1 must not be stored twice as endpoints."""
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(snapshot["id"], tracker["id"], [{
        "flight_key": key, "source": "google_flights", "price": 500.0, "currency": "EUR",
    }])
    async with db_conn.execute(
        "SELECT count(*) FROM flight_prices WHERE flight_key = ?", (key,)
    ) as cur:
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_two_sources_holding_the_same_price_keep_separate_runs(db_path, db_conn):
    """Runs are per SOURCE: Kayak and Google run on independent cadences and
    fail independently, so merging their runs would make one source's silence
    look like the other's observation."""
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    for _ in range(3):
        snapshot = await create_snapshot(tracker["id"], results_count=2)
        await insert_flight_prices(snapshot["id"], tracker["id"], [
            {"flight_key": key, "source": "google_flights", "price": 500.0, "currency": "EUR"},
            {"flight_key": key, "source": "kayak", "price": 500.0, "currency": "EUR"},
        ])
    async with db_conn.execute(
        "SELECT count(DISTINCT source) FROM flight_prices WHERE flight_key = ?", (key,)
    ) as cur:
        assert (await cur.fetchone())[0] == 2
