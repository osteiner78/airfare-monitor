"""Duplicate Kayak offers, and the startup search storm.

1. DUPLICATE OFFERS. Kayak lists one itinerary several times when it sells it
   under several fare brands. Observed 2026-08-11 on GRU-GVA:

       7:20 pm - 10:25 pm+1  LATAM Airlines, Iberia  EUR641  "Light + Economy Cabin"
       7:20 pm - 10:25 pm+1  LATAM Airlines          EUR641  "Light"

   `_first_carrier` collapses the carrier-list difference (plan 019, so Kayak
   rows can merge with Google's) and `flight_key` carries no fare brand, so
   both arrive indistinguishable. The slot was consumed ON THE PAGE, before
   extraction, so deduping alone would return top_n-1 rows -- hence the
   over-fetch.

2. STARTUP STORM. `_startup` registered every job with run_immediately=True,
   so every `--reload` (i.e. every edit under backend/) fired a live search for
   every active tracker. Measured: 144 snapshots in a day against ~24 expected,
   78 of them in the single hour spent editing code.
"""

import pytest

from backend.sources.kayak import _OVERFETCH_ROWS, KayakSource


def _row(airline, price, dep="2026-08-21T19:20:00", arr="2026-08-22T22:25:00"):
    return {"airline": airline, "price": price,
            "departure_time": dep, "arrival_time": arr}


# --- 1. dedupe ---

def test_identical_offers_collapse():
    rows = [_row("LATAM Airlines", 641.0), _row("LATAM Airlines", 641.0)]
    assert len(KayakSource._dedupe_rows(rows)) == 1


def test_same_flight_at_a_different_price_is_kept():
    """Different money is different information, even for one itinerary."""
    rows = [_row("LATAM Airlines", 641.0), _row("LATAM Airlines", 705.0)]
    assert len(KayakSource._dedupe_rows(rows)) == 2


def test_same_price_on_a_different_itinerary_is_kept():
    rows = [_row("LATAM Airlines", 641.0),
            _row("LATAM Airlines", 641.0, arr="2026-08-22T18:05:00")]
    assert len(KayakSource._dedupe_rows(rows)) == 2


def test_a_different_carrier_is_kept():
    rows = [_row("LATAM Airlines", 641.0), _row("Iberia", 641.0)]
    assert len(KayakSource._dedupe_rows(rows)) == 2


def test_carrier_casing_and_spacing_do_not_create_a_false_difference():
    """Normalised the same way make_flight_key normalises, or two rows that
    share a flight_key would still both be stored."""
    rows = [_row("LATAM Airlines", 641.0), _row("latam   airlines", 641.0)]
    assert len(KayakSource._dedupe_rows(rows)) == 1


def test_the_cheapest_duplicate_survives():
    """Rows arrive cheapest-first, so first-wins must keep the cheaper row."""
    rows = [_row("LATAM Airlines", 641.0), _row("LATAM  Airlines", 641.0)]
    kept = KayakSource._dedupe_rows(rows)
    assert kept[0]["price"] == 641.0


def test_order_is_preserved():
    rows = [_row("A", 100.0), _row("B", 200.0), _row("A", 100.0), _row("C", 300.0)]
    assert [r["airline"] for r in KayakSource._dedupe_rows(rows)] == ["A", "B", "C"]


def test_overfetch_is_positive_or_dedupe_shrinks_the_result_set():
    assert _OVERFETCH_ROWS >= 1, (
        "without over-fetching, every collapsed duplicate costs a stored row"
    )


# --- 2. startup ---

@pytest.mark.asyncio
async def test_a_tracker_with_no_snapshots_searches_immediately(db_path):
    from backend.db import create_tracker
    from backend.main import _tracker_is_overdue

    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-08-21", interval_minutes=60)
    assert await _tracker_is_overdue(tracker) is True


@pytest.mark.asyncio
async def test_a_just_searched_tracker_does_not_research_on_reload(db_path):
    """The storm: an edit-reload cycle must not re-run a search that finished
    seconds ago."""
    from backend.db import create_snapshot, create_tracker
    from backend.main import _tracker_is_overdue

    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-08-21", interval_minutes=60)
    await create_snapshot(tracker["id"], results_count=1)

    assert await _tracker_is_overdue(tracker) is False


@pytest.mark.asyncio
async def test_a_stale_tracker_still_searches_immediately(db_path):
    """The behaviour worth keeping: a real restart after downtime refreshes at
    once rather than waiting a whole interval."""
    import os

    import aiosqlite

    from backend.db import create_snapshot, create_tracker
    from backend.main import _tracker_is_overdue

    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-08-21", interval_minutes=60)
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        await db.execute("UPDATE snapshots SET searched_at = '2026-01-01 00:00:00' "
                         "WHERE id = ?", (snapshot["id"],))
        await db.commit()

    assert await _tracker_is_overdue(tracker) is True


@pytest.mark.asyncio
async def test_an_unparseable_timestamp_errs_toward_searching(db_path):
    """Refusing to search because a timestamp could not be parsed would leave a
    tracker silently un-refreshed; a redundant search is the cheaper mistake."""
    import os

    import aiosqlite

    from backend.db import create_snapshot, create_tracker
    from backend.main import _tracker_is_overdue

    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-08-21", interval_minutes=60)
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        await db.execute("UPDATE snapshots SET searched_at = 'not-a-date' WHERE id = ?",
                         (snapshot["id"],))
        await db.commit()

    assert await _tracker_is_overdue(tracker) is True
