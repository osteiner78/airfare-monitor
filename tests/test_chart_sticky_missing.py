"""Regression: a sticky all-time-low flight that drops out of the latest
snapshot must keep its chart line.

The original bug (found 2026-08-06): `window.allFlights` is built server-side
by skipping any flight whose delta is "missing", and `filters.js::applyFilters`
derived its `stickyExtras` from `allFlights` alone -- so a flight that was once
in the top N but is absent from the current snapshot could never survive into
the redrawn chart, and its line vanished the moment the page's JS ran. The
"Historical best" badge (read straight from the DB) then showed a price no
line on the chart reached.

This is exactly tracker 20's situation: the EUR654 Kayak-only fare was seen
once and never again, because Kayak runs on its own cadence and only
participates in some snapshots.

The fix (commit e1a42c2) gives every chart dataset a `flight_key` and has
`filters.js` fall back to the server's own `window.chartData` for sticky keys
absent from `allFlights`. These tests pin the server half of that contract --
without `flight_key` on the datasets the client fallback silently matches
nothing and the bug returns with no test failing.
"""

import json
import os
import re

import aiosqlite
import pytest


def _extract_js_global(text: str, name: str):
    match = re.search(r"window\." + re.escape(name) + r" = (.*?);</script>", text, re.DOTALL)
    if match is None:
        return None
    return json.loads(match.group(1))


async def _set_searched_at(snapshot_id: int, searched_at: str) -> None:
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        await db.execute(
            "UPDATE snapshots SET searched_at = ? WHERE id = ?", (searched_at, snapshot_id)
        )
        await db.commit()


async def _tracker_with_a_vanished_cheap_flight():
    """Snapshot 1 carries a cheap fare; snapshot 2 does not. The cheap fare is
    the all-time low and is sticky, but is missing from the latest snapshot."""
    from backend.db import create_snapshot, create_tracker, insert_flight_prices

    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-08-21")

    s1 = await create_snapshot(tracker["id"], results_count=2)
    await _set_searched_at(s1["id"], "2026-08-06 01:29:40")
    await insert_flight_prices(s1["id"], tracker["id"], [
        {"flight_key": "multiple airlines|2026-08-21T03:50:00|2026-08-22T22:20:00",
         "source": "kayak", "price": 654.0, "currency": "EUR",
         "airline": "Multiple airlines", "flight_number": "",
         "departure_time": "2026-08-21T03:50:00", "arrival_time": "2026-08-22T22:20:00"},
        {"flight_key": "iberia|2026-08-21T14:00:00|2026-08-22T11:05:00",
         "source": "google_flights", "price": 800.0, "currency": "EUR",
         "airline": "Iberia", "flight_number": "IB 1",
         "departure_time": "2026-08-21T14:00:00", "arrival_time": "2026-08-22T11:05:00"},
    ])

    s2 = await create_snapshot(tracker["id"], results_count=1)
    await _set_searched_at(s2["id"], "2026-08-11 01:31:12")
    await insert_flight_prices(s2["id"], tracker["id"], [
        {"flight_key": "iberia|2026-08-21T14:00:00|2026-08-22T11:05:00",
         "source": "google_flights", "price": 815.0, "currency": "EUR",
         "airline": "Iberia", "flight_number": "IB 1",
         "departure_time": "2026-08-21T14:00:00", "arrival_time": "2026-08-22T11:05:00"},
    ])
    return tracker


@pytest.mark.asyncio
async def test_chart_datasets_carry_flight_key(db_path, client):
    """The join column the client fallback needs. If this field disappears,
    `filters.js` matches nothing and the vanishing-line bug returns silently."""
    tracker = await _tracker_with_a_vanished_cheap_flight()

    page = (await client.get(f"/trackers/{tracker['id']}")).text
    datasets = _extract_js_global(page, "chartData")

    assert datasets, "no chartData emitted"
    assert all("flight_key" in d for d in datasets), \
        "a chart dataset has no flight_key -- the sticky fallback cannot match it"


@pytest.mark.asyncio
async def test_a_sticky_flight_missing_from_the_latest_snapshot_keeps_its_line(db_path, client):
    """The bug itself, at the server boundary: every sticky key absent from
    allFlights must still be reachable through chartData."""
    tracker = await _tracker_with_a_vanished_cheap_flight()

    page = (await client.get(f"/trackers/{tracker['id']}")).text
    datasets = _extract_js_global(page, "chartData")
    sticky = _extract_js_global(page, "stickyFlightKeys")
    all_flights = _extract_js_global(page, "allFlights")

    present = {f["flight_key"] for f in all_flights}
    dataset_keys = {d["flight_key"] for d in datasets}
    uncovered = [k for k in sticky if k not in present and k not in dataset_keys]

    assert not uncovered, f"sticky flights would vanish from the chart: {uncovered}"


@pytest.mark.asyncio
async def test_the_all_time_low_is_reachable_on_the_chart(db_path, client):
    """The user-visible symptom: the 'Historical best' badge must not show a
    price that no chart line ever dips to."""
    from backend.db import get_historical_best_price

    tracker = await _tracker_with_a_vanished_cheap_flight()
    historical_best = await get_historical_best_price(tracker["id"])

    page = (await client.get(f"/trackers/{tracker['id']}")).text
    datasets = _extract_js_global(page, "chartData")

    lowest_on_chart = min(
        (point["y"] for d in datasets for point in d.get("data", [])), default=None
    )
    assert lowest_on_chart is not None
    assert lowest_on_chart <= historical_best, (
        f"badge shows {historical_best} but the cheapest charted point is "
        f"{lowest_on_chart} -- the all-time-low line is missing"
    )
