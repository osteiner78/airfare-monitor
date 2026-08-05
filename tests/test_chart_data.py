import json
import os
import re

import aiosqlite
import pytest


def _extract_js_global(text: str, name: str):
    """Pull `window.<name> = <json>;</script>` out of a rendered page and parse it.
    Returns None when the global is not emitted (lets fail-first tests fail cleanly)."""
    match = re.search(r"window\." + re.escape(name) + r" = (.*?);</script>", text, re.DOTALL)
    if match is None:
        return None
    return json.loads(match.group(1))


async def _set_searched_at(snapshot_id: int, searched_at: str) -> None:
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        await db.execute(
            "UPDATE snapshots SET searched_at = ? WHERE id = ?",
            (searched_at, snapshot_id),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n(db_path):
    from backend.db import create_snapshot, create_tracker, get_sticky_top_flight_keys, insert_flight_prices

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=3)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "test|VY|6201|2026-01-01T00:00:00", "source": "test", "price": 33.0, "currency": "EUR"},
        {"flight_key": "test|U2|7108|2026-01-01T00:00:00", "source": "test", "price": 45.0, "currency": "EUR"},
        {"flight_key": "test|LH|1234|2026-01-01T00:00:00", "source": "test", "price": 100.0, "currency": "EUR"},
    ])

    keys = await get_sticky_top_flight_keys(tracker["id"], 2)
    assert len(keys) == 2
    assert "test|VY|6201|2026-01-01T00:00:00" in keys
    assert "test|U2|7108|2026-01-01T00:00:00" in keys


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots(db_path):
    from backend.db import create_tracker, get_sticky_top_flight_keys

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    keys = await get_sticky_top_flight_keys(tracker["id"], 5)
    assert keys == set() or len(keys) == 0


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker(db_path):
    from backend.db import get_sticky_top_flight_keys

    keys = await get_sticky_top_flight_keys(999, 5)
    assert keys == set() or len(keys) == 0


@pytest.mark.asyncio
async def test_get_sticky_top_flight_keys_returns_top_n_distinct_flights_when_a_key_repeats_in_a_snapshot(db_path):
    """FAILURE-MODE for plan 017 phase 1.7. The ROW_NUMBER() window ranks ROWS
    within a snapshot, so once two sources can quote the same physical flight
    (flight_key no longer carries source), the duplicate eats a rank slot and
    the chart silently tracks fewer than top_n distinct flights."""
    from backend.db import create_snapshot, create_tracker, get_sticky_top_flight_keys, insert_flight_prices

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=4)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "VY|6201|2026-01-01T00:00:00", "source": "google_flights", "price": 33.0, "currency": "EUR"},
        {"flight_key": "VY|6201|2026-01-01T00:00:00", "source": "kayak", "price": 35.0, "currency": "EUR"},
        {"flight_key": "U2|7108|2026-01-01T00:00:00", "source": "google_flights", "price": 45.0, "currency": "EUR"},
        {"flight_key": "LH|1234|2026-01-01T00:00:00", "source": "google_flights", "price": 100.0, "currency": "EUR"},
    ])

    keys = await get_sticky_top_flight_keys(tracker["id"], 2)
    assert keys == {"VY|6201|2026-01-01T00:00:00", "U2|7108|2026-01-01T00:00:00"}


@pytest.mark.asyncio
async def test_chart_datasets_limited_to_sticky_top_n(client):
    from backend.db import create_snapshot, create_tracker, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert '"label": "Vueling 6201"' in response.text


# --- NEW-BEHAVIOR (plan 009): chart datasets carry a server-assigned color ---

@pytest.mark.asyncio
async def test_chart_dataset_includes_color_field(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert '"color"' in response.text


@pytest.mark.asyncio
async def test_chart_dataset_color_is_first_palette_color_for_single_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "#4a90d9" in response.text


# --- NEW-BEHAVIOR (plan 010, Phase 1): color follows price rank, not history order ---

@pytest.mark.asyncio
async def test_color_assigned_by_price_rank_not_history_order(client):
    # Flight B appears first in history (earlier snapshot) but A is cheaper in the
    # latest snapshot. Color must track price rank: cheapest -> first palette color.
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })

    key_a = "test|AA|1|2026-01-01T00:00:00"
    key_b = "test|BB|2|2026-01-01T00:00:00"

    snap1 = await create_snapshot(1, results_count=1)
    await _set_searched_at(snap1["id"], "2026-01-01 00:00:00")
    await insert_flight_prices(snap1["id"], 1, [{
        "flight_key": key_b, "source": "test", "price": 200.0, "currency": "EUR",
        "airline": "Bee", "flight_number": "BB2",
        "departure_time": "2026-01-01T08:00:00", "arrival_time": "2026-01-01T10:00:00",
        "duration_min": 120, "stops": 0,
    }])

    snap2 = await create_snapshot(1, results_count=2)
    await _set_searched_at(snap2["id"], "2026-01-02 00:00:00")
    await insert_flight_prices(snap2["id"], 1, [
        {
            "flight_key": key_a, "source": "test", "price": 50.0, "currency": "EUR",
            "airline": "Ayy", "flight_number": "AA1",
            "departure_time": "2026-01-02T08:00:00", "arrival_time": "2026-01-02T10:00:00",
            "duration_min": 90, "stops": 0,
        },
        {
            "flight_key": key_b, "source": "test", "price": 200.0, "currency": "EUR",
            "airline": "Bee", "flight_number": "BB2",
            "departure_time": "2026-01-02T08:00:00", "arrival_time": "2026-01-02T10:00:00",
            "duration_min": 120, "stops": 0,
        },
    ])

    response = await client.get("/trackers/1")
    datasets = _extract_js_global(response.text, "chartData")
    color_by_label = {d["label"]: d["color"] for d in datasets}
    assert color_by_label["Ayy AA1"] == "#4a90d9"
    assert color_by_label["Bee BB2"] == "#e67e22"


# --- NEW-BEHAVIOR (plan 019, Phase 2): the chart-point merge must survive a
# searched_at tie. _build_detail_context collapses the rows of one
# (flight_key, snapshot_id) into a single point by comparing against the
# previous row only, so same-snapshot rows have to arrive adjacent. Ordering
# by searched_at alone does not guarantee that when two snapshots share a
# second-resolution timestamp -- and plan 019's identity change made a key
# repeat within a snapshot 27x more common, so a tie now lands on colliding
# rows rather than passing harmlessly through.

@pytest.mark.asyncio
async def test_two_snapshots_sharing_a_timestamp_stay_two_points_with_a_repeated_key(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })

    key = "swiss|2026-01-01T08:00:00|2026-01-01T10:00:00"
    tied_at = "2026-01-01 00:00:00"

    def _row(price: float, source: str):
        return {
            "flight_key": key, "source": source, "price": price, "currency": "EUR",
            "airline": "SWISS", "flight_number": "",
            "departure_time": "2026-01-01T08:00:00",
            "arrival_time": "2026-01-01T10:00:00",
            "duration_min": 120, "stops": 0,
        }

    # Each snapshot carries the SAME key twice (two sources quoting one
    # physical flight), which is the case the identity change makes common.
    snap1 = await create_snapshot(1, results_count=2)
    await _set_searched_at(snap1["id"], tied_at)
    await insert_flight_prices(snap1["id"], 1, [_row(100.0, "a"), _row(120.0, "b")])

    snap2 = await create_snapshot(1, results_count=2)
    await _set_searched_at(snap2["id"], tied_at)
    await insert_flight_prices(snap2["id"], 1, [_row(300.0, "a"), _row(320.0, "b")])

    response = await client.get("/trackers/1")
    datasets = _extract_js_global(response.text, "chartData")

    assert datasets, "chartData was not emitted at all"
    series = [d for d in datasets if d["data"]]
    assert series, "no dataset carried any history points"
    points = series[0]["data"]

    # Two snapshots -> two points; four rows must not become four points, and
    # the two rows of each snapshot must merge to that snapshot's cheapest.
    assert len(points) == 2
    assert [p["y"] for p in points] == [100.0, 300.0]
