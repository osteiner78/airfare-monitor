"""Blend the latest observation of each source, instead of reading one snapshot.

Sources run on independent cadences (Kayak ~hourly and only when due, fli every
tick) and fail independently. Reading a single snapshot meant a Google-only
cycle made Kayak's rows render as "missing" -- which claims those fares
disappeared, when the truth was only that Kayak had not run. Worse, the
missing-row reconstruction looked back exactly ONE snapshot, so two Google-only
cycles in a row dropped Kayak from the page entirely. That is what made Kayak
results look like they never appeared at all.

The fix is a read-time join over each source's most recent observation.
Nothing is written: carrying rows forward into new snapshots would fabricate
chart points, and `historical_best_price` is MIN over all rows and never
recomputed, so a re-inserted stale price would distort the all-time low
permanently.
"""

import os
import re

import aiosqlite
import pytest

TRACKER = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}

KAYAK_KEY = "tap air portugal|2026-08-21T20:45:00|2026-08-22T17:15:00"
GOOGLE_KEY = "iberia|2026-08-21T14:00:00|2026-08-22T11:05:00"


def _row(flight_key, source, price, **over):
    row = {
        "flight_key": flight_key, "source": source, "price": price,
        "currency": "EUR", "airline": "TAP AIR PORTUGAL", "flight_number": "",
        "departure_time": "2026-08-21T20:45:00",
        "arrival_time": "2026-08-22T17:15:00",
        "duration_min": 1230, "stops": 1,
    }
    row.update(over)
    return row


async def _at(snapshot_id: int, searched_at: str) -> None:
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        await db.execute("UPDATE snapshots SET searched_at = ? WHERE id = ?",
                         (searched_at, snapshot_id))
        await db.commit()


async def _kayak_then_google_only(client, google_only_cycles: int = 1):
    """The exact production shape: Kayak runs, then N Google-only cycles."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER)

    s1 = await create_snapshot(1, results_count=2)
    await _at(s1["id"], "2026-08-11 03:15:00")
    await insert_flight_prices(s1["id"], 1, [
        _row(KAYAK_KEY, "kayak", 784.0),
        _row(GOOGLE_KEY, "google_flights", 815.0, airline="Iberia",
             departure_time="2026-08-21T14:00:00",
             arrival_time="2026-08-22T11:05:00"),
    ])

    for i in range(google_only_cycles):
        s = await create_snapshot(1, results_count=1)
        await _at(s["id"], f"2026-08-11 03:{20 + i * 5:02d}:00")
        await insert_flight_prices(s["id"], 1, [
            _row(GOOGLE_KEY, "google_flights", 815.0, airline="Iberia",
                 departure_time="2026-08-21T14:00:00",
                 arrival_time="2026-08-22T11:05:00"),
        ])
    return await client.get("/trackers/1")


@pytest.mark.asyncio
async def test_kayak_survives_one_google_only_cycle(client):
    page = (await _kayak_then_google_only(client, 1)).text
    assert "€784" in page
    assert "Kayak" in page


@pytest.mark.asyncio
async def test_kayak_survives_several_google_only_cycles(client):
    """The original failure: the one-snapshot lookback meant two Google-only
    cycles erased Kayak completely. This is the regression that matters."""
    page = (await _kayak_then_google_only(client, 3)).text
    assert "€784" in page, "Kayak vanished after repeated Google-only cycles"
    assert "Kayak" in page


@pytest.mark.asyncio
async def test_a_stale_kayak_row_is_not_labelled_missing(client):
    """'missing' means the fare is gone. A source that did not run is a
    different fact and must not borrow that label."""
    page = (await _kayak_then_google_only(client, 2)).text
    rows = re.findall(r'<tr[^>]*data-flight-key="([^"]*)"[^>]*class="([^"]*)"', page)
    for key, classes in rows:
        if key == KAYAK_KEY:
            assert "row-missing" not in classes, \
                "a source that simply did not run was marked as a vanished fare"


@pytest.mark.asyncio
async def test_best_now_uses_the_cheapest_blended_price(client):
    """The user-visible payoff: the headline stops swinging by ~EUR30 with
    Kayak's cadence, because the cheapest known fare stays in view."""
    page = (await _kayak_then_google_only(client, 2)).text
    assert "Best now: €784" in page, \
        "headline fell back to the fresher-but-pricier Google row"


@pytest.mark.asyncio
async def test_a_source_older_than_the_staleness_cap_is_dropped(client):
    """A fare from many cycles ago is not 'current' in any useful sense.
    Cap is 2x the tracker interval; default interval is 60 min."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER)

    s1 = await create_snapshot(1, results_count=1)
    await _at(s1["id"], "2026-08-11 00:00:00")
    await insert_flight_prices(s1["id"], 1, [_row(KAYAK_KEY, "kayak", 784.0)])

    s2 = await create_snapshot(1, results_count=1)
    await _at(s2["id"], "2026-08-11 09:00:00")  # 9h later, way past 2x60min
    await insert_flight_prices(s2["id"], 1, [
        _row(GOOGLE_KEY, "google_flights", 815.0, airline="Iberia",
             departure_time="2026-08-21T14:00:00",
             arrival_time="2026-08-22T11:05:00"),
    ])

    page = (await client.get("/trackers/1")).text
    # It stays the all-time low -- that is a real historical price and blending
    # must not touch it. What must NOT happen is it being presented as current.
    assert "Historical best: €784" in page
    assert "Best now: €784" not in page, "a 9-hour-old fare drove the headline"
    assert f'data-flight-key="{KAYAK_KEY}"' not in page, \
        "a 9-hour-old fare was still listed as a current result"
    assert "€815" in page


@pytest.mark.asyncio
async def test_deltas_compare_a_source_against_its_own_previous_run(client):
    """Comparing Kayak-now against a Google-only snapshot in between would
    invent a price movement that never happened."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER)

    s1 = await create_snapshot(1, results_count=1)
    await _at(s1["id"], "2026-08-11 01:00:00")
    await insert_flight_prices(s1["id"], 1, [_row(KAYAK_KEY, "kayak", 784.0)])

    s2 = await create_snapshot(1, results_count=1)
    await _at(s2["id"], "2026-08-11 01:30:00")
    await insert_flight_prices(s2["id"], 1, [
        _row(GOOGLE_KEY, "google_flights", 815.0, airline="Iberia",
             departure_time="2026-08-21T14:00:00",
             arrival_time="2026-08-22T11:05:00"),
    ])

    s3 = await create_snapshot(1, results_count=1)
    await _at(s3["id"], "2026-08-11 02:00:00")
    await insert_flight_prices(s3["id"], 1, [_row(KAYAK_KEY, "kayak", 784.0)])

    page = (await client.get("/trackers/1")).text
    assert "price-badge same" in page, \
        "Kayak's unchanged price was compared against a different source"
    assert "price-badge down" not in page


@pytest.mark.asyncio
async def test_nothing_is_written_back_to_the_database(client):
    """Blending is a read-time join. A carried-forward row inserted into a new
    snapshot would become a fake chart point and permanently distort
    historical_best_price, which is MIN over all rows and never recomputed."""
    from backend.db import get_flight_prices_for_snapshots

    await _kayak_then_google_only(client, 2)

    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT snapshot_id, COUNT(*) n FROM flight_prices "
            "WHERE source = 'kayak' GROUP BY snapshot_id"
        ) as cur:
            kayak_rows = [dict(r) for r in await cur.fetchall()]

    assert len(kayak_rows) == 1, \
        f"kayak rows were duplicated into later snapshots: {kayak_rows}"
    assert kayak_rows[0]["n"] == 1

    # And the helper itself must not invent rows.
    assert await get_flight_prices_for_snapshots([]) == []


@pytest.mark.asyncio
async def test_the_google_fallback_is_not_blended_as_a_separate_source(client):
    """`fast_flights` runs ONLY when fli returns nothing (FallbackSource), so
    they are alternate scrapers of one upstream, not two opinions. Blending
    them separately resurrected a stale fallback set beside fresh primary rows
    -- the same flights listed twice at different ages."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER)

    # fli failed; the fallback served this cycle.
    s1 = await create_snapshot(1, results_count=1)
    await _at(s1["id"], "2026-08-11 02:00:00")
    await insert_flight_prices(s1["id"], 1, [
        _row(GOOGLE_KEY, "fast_flights", 957.0, airline="Iberia",
             departure_time="2026-08-21T14:00:00",
             arrival_time="2026-08-22T11:05:00"),
    ])

    # fli recovered and quotes the same flight cheaper.
    s2 = await create_snapshot(1, results_count=1)
    await _at(s2["id"], "2026-08-11 02:30:00")
    await insert_flight_prices(s2["id"], 1, [
        _row(GOOGLE_KEY, "google_flights", 815.0, airline="Iberia",
             departure_time="2026-08-21T14:00:00",
             arrival_time="2026-08-22T11:05:00"),
    ])

    page = (await client.get("/trackers/1")).text
    assert "€815" in page
    assert "€957" not in page, \
        "the superseded fallback quote was blended back in alongside the primary"
    assert "Best now: €815" in page
