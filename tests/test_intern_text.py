"""Plan 028 Phase 5 — intern legs_json and booking_url into side tables.

NEW-BEHAVIOR and FAILURE-MODE. All fail until Phase 5 lands.

Measured against production on 2026-08-15: legs_json holds 275,980 rows of
2,993 distinct values, and COUNT(DISTINCT flight_key||legs_json) is ALSO 2,993
-- the legs are a pure function of the flight, never varying per snapshot, so
interning by value is exactly correct. booking_url is 276,493 rows holding 30
distinct strings. 121 MB of a 182 MB table.

Lossless is the whole point: this phase moves TEXT, never identity or money.
Every test below is about round-tripping, not about size.
"""

import pytest


def _row(flight_key, legs_json="[]", booking_url="https://example.com", price=100.0):
    return {
        "flight_key": flight_key, "source": "google_flights", "price": price,
        "currency": "EUR", "legs_json": legs_json, "booking_url": booking_url,
    }


@pytest.mark.asyncio
async def test_two_rows_with_identical_legs_share_one_legs_row(db_path, db_conn):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    legs = '[{"from":"GRU","to":"ZRH"}]'
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        _row("a|1|2", legs_json=legs), _row("b|1|2", legs_json=legs),
    ])
    async with db_conn.execute("SELECT count(*) FROM flight_legs") as cur:
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_interned_legs_round_trip_to_the_original_json(db_path):
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    legs = '[{"from":"GRU","to":"ZRH","flight":"LX 93"}]'
    await insert_flight_prices(snapshot["id"], tracker["id"], [_row("a|1|2", legs_json=legs)])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["legs_json"] == legs


@pytest.mark.asyncio
async def test_an_empty_legs_json_is_interned_once_not_per_row(db_path, db_conn):
    """"[]" is what every Kayak row carries, so it is the single most repeated
    value in the table."""
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=3)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        _row("a|1|2"), _row("b|1|2"), _row("c|1|2"),
    ])
    async with db_conn.execute("SELECT count(*) FROM flight_legs") as cur:
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_two_rows_with_the_same_booking_url_share_one_url_row(db_path, db_conn):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        _row("a|1|2"), _row("b|1|2"),
    ])
    async with db_conn.execute("SELECT count(*) FROM booking_urls") as cur:
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_a_unicode_booking_url_round_trips(db_path):
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    url = "https://example.com/voos?de=São Paulo&para=Zürich"
    await insert_flight_prices(snapshot["id"], tracker["id"], [_row("a|1|2", booking_url=url)])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["booking_url"] == url


@pytest.mark.asyncio
async def test_a_null_legs_json_stays_null(db_path):
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(snapshot["id"], tracker["id"], [_row("a|1|2", legs_json=None)])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["legs_json"] is None


@pytest.mark.asyncio
async def test_an_empty_string_url_is_distinct_from_a_null_url(db_path):
    """The backfill script writes booking_url="" while sources write real URLs;
    collapsing the two would rewrite history."""
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        _row("a|1|2", booking_url=""), _row("b|1|2", booking_url=None),
    ])
    rows = sorted(await get_flight_prices_for_snapshot(snapshot["id"]),
                  key=lambda r: r["flight_key"])
    assert rows[0]["booking_url"] == "" and rows[1]["booking_url"] is None


@pytest.mark.asyncio
async def test_a_very_large_legs_json_round_trips(db_path):
    """A multi-leg itinerary's JSON is the largest text this table stores."""
    import json
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    legs = json.dumps([{"from": "GRU", "to": "ZRH", "n": i} for i in range(500)])
    await insert_flight_prices(snapshot["id"], tracker["id"], [_row("a|1|2", legs_json=legs)])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["legs_json"] == legs


@pytest.mark.asyncio
async def test_interning_does_not_change_the_stored_price(db_path):
    """This phase moves text, not money."""
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(snapshot["id"], tracker["id"], [_row("a|1|2", price=654.0)])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["price"] == 654.0
