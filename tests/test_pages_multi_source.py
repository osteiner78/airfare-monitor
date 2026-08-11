import json
import re

import pytest

TRACKER_FORM = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}

SHARED_KEY = "TP|TP84|2026-08-21T00:45:00"


def _extract_js_global(text: str, name: str):
    """Pull `window.<name> = <json>;</script>` out of a rendered page and parse it.
    Returns None when the global is absent, so fail-first tests fail on a real
    assertion rather than a regex/JSON crash."""
    match = re.search(r"window\." + re.escape(name) + r" = (.*?);</script>", text, re.DOTALL)
    if match is None:
        return None
    return json.loads(match.group(1))


def _price_row(flight_key, source, price, **overrides):
    row = {
        "flight_key": flight_key,
        "source": source,
        "price": price,
        "currency": "EUR",
        "airline": "TP",
        "flight_number": "TP84",
        "departure_time": "2026-08-21T00:45:00",
        "arrival_time": "2026-08-21T22:30:00",
        "duration_min": 1305,
        "stops": 1,
    }
    row.update(overrides)
    return row


# --- previous-snapshot dedup (delta computation) ---
# get_flight_prices_for_snapshot returns rows ORDER BY price ASC. Once the
# same flight_key can appear more than once per snapshot (plan 017 phase 1:
# flight_key no longer includes source), a naive
# `{p["flight_key"]: p["price"] for p in rows}` dict comprehension keeps the
# LAST-seen row per key -- which, given ascending price order, is the most
# EXPENSIVE quote, not the cheapest. These tests pin the correct behavior:
# cheapest-per-key wins.

@pytest.mark.asyncio
async def test_price_delta_uses_cheapest_previous_price_when_flight_key_quoted_by_two_sources(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    prev_snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(prev_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])

    current_snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(current_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    # Same price as the cheapest previous quote (711) => "same" badge, not a
    # "down" badge from a wrongly-used previous price of 785.
    assert "price-badge down" not in response.text
    assert "price-badge same" in response.text


@pytest.mark.asyncio
async def test_a_source_that_did_not_run_keeps_reporting_its_own_last_view(client):
    """Rewritten for the blended model (2026-08-11), replacing
    test_missing_flight_reconstruction_uses_cheapest_historical_price.

    That test asserted this scenario rendered SHARED_KEY as a *missing* row at
    Google's older EUR711 quote. Under blending it is a live Kayak row at
    EUR785, and that is the more truthful reading: Kayak's most recent
    observation still lists the flight at 785 and Kayak has not run since,
    while Google's NEWEST run no longer lists the flight at all -- so 711 is
    the stale number, not 785. Showing 711 as the flight's price would be the
    original bug inverted.

    The replaced test's real intent -- cheapest quote wins when one flight_key
    is quoted by several sources -- is still covered by
    test_price_delta_uses_cheapest_previous_price_... above and by
    test_missing_row_still_uses_the_cheapest_quote_of_its_own_source below.
    """
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    prev_snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(prev_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])

    current_snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(current_snapshot["id"], 1, [
        _price_row("LX|LX1234|2026-08-21T08:00:00", "google_flights", 900.0,
                   airline="LX", flight_number="LX1234",
                   departure_time="2026-08-21T08:00:00"),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200

    # Kayak's last view survives the Google-only cycle...
    assert "€785" in response.text
    # ...and wins "Best now", being cheaper than Google's fresh EUR900.
    assert "Best now: €785" in response.text
    # Google's fresh row is still there.
    assert "€900" in response.text


@pytest.mark.asyncio
async def test_missing_row_still_uses_the_cheapest_quote_of_its_own_source(client):
    """The replaced test's surviving intent: when a flight really does drop out
    of a source that DID run, its reconstructed row uses that source's cheapest
    quote, not its most expensive. Both quotes here belong to google_flights,
    so blending cannot keep the flight alive from elsewhere."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    prev_snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(prev_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "google_flights", 785.0),
    ])

    current_snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(current_snapshot["id"], 1, [
        _price_row("LX|LX1234|2026-08-21T08:00:00", "google_flights", 900.0,
                   airline="LX", flight_number="LX1234",
                   departure_time="2026-08-21T08:00:00"),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "€711" in response.text
    assert "€785" not in response.text


# --- the actual motivating bug: phantom missing/new when sources rotate ---

@pytest.mark.asyncio
async def test_flight_not_marked_missing_when_still_quoted_by_a_different_source(client):
    """The core reason plan 017 chose full cross-source identity over
    summary-only attribution: fli quotes a flight one run, Kayak quotes the
    SAME physical flight (fli having failed/not returned it) the next run.
    With a shared flight_key this must NOT render as one flight disappearing
    and a new one appearing."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    prev_snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(prev_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
    ])

    current_snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(current_snapshot["id"], 1, [
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "row-missing" not in response.text


# --- results table stays transparent: does NOT collapse multi-source rows ---

@pytest.mark.asyncio
async def test_results_table_shows_every_source_row_even_when_flight_key_repeats(client):
    """Cross-source identity is for chart/history/missing-diff purposes only.
    The results table itself must keep showing each source's own quote as its
    own row, so the user can compare and pick which one to book through."""
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "€711" in response.text
    assert "€785" in response.text


# --- chart inputs DO collapse multi-source rows ---
# The results table shows one row per DB row (above). window.allFlights and the
# chart colour ranking are the opposite case: they are per-FLIGHT, and a
# duplicated flight_key there double-enters filters.js's client-side price-rank
# top-N and shifts every subsequent colour slot. These two things must not be
# conflated -- plan 017 v1 fixed three dict-comprehension sites and missed both
# of these, which are list-append sites rather than dict-overwrite sites.

@pytest.mark.asyncio
async def test_window_all_flights_has_one_entry_per_flight_key(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    snapshot = await create_snapshot(1, results_count=3)
    await insert_flight_prices(snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
        _price_row("LX|LX1234|2026-08-21T08:00:00", "google_flights", 800.0,
                   airline="LX", flight_number="LX1234",
                   departure_time="2026-08-21T08:00:00"),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None

    keys = [f["flight_key"] for f in all_flights]
    assert len(keys) == len(set(keys))
    assert sorted(keys) == sorted([SHARED_KEY, "LX|LX1234|2026-08-21T08:00:00"])


@pytest.mark.asyncio
async def test_window_all_flights_entry_uses_cheapest_price_for_a_duplicated_key(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)

    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None

    entries = [f for f in all_flights if f["flight_key"] == SHARED_KEY]
    assert len(entries) == 1
    assert entries[0]["price"] == 711.0


@pytest.mark.asyncio
async def test_chart_top_n_counts_distinct_flights_not_rows(client):
    """_assign_chart_colors assigns by list position, so a flight_key appearing
    twice consumes two palette slots and pushes every later flight's colour off
    by one. Colour rank must follow price rank over DISTINCT flights: cheapest
    -> CHART_COLORS[0], second-cheapest -> CHART_COLORS[1]."""
    from backend.db import create_snapshot, insert_flight_prices
    from backend.pages import CHART_COLORS

    await client.post("/api/trackers", json=TRACKER_FORM)

    snapshot = await create_snapshot(1, results_count=4)
    await insert_flight_prices(snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
        _price_row("LX|LX1234|2026-08-21T08:00:00", "google_flights", 800.0,
                   airline="LX", flight_number="LX1234",
                   departure_time="2026-08-21T08:00:00"),
        _price_row("AF|AF123|2026-08-21T09:00:00", "google_flights", 900.0,
                   airline="AF", flight_number="AF123",
                   departure_time="2026-08-21T09:00:00"),
    ])

    response = await client.get("/trackers/1")
    chart_data = _extract_js_global(response.text, "chartData")
    assert chart_data is not None

    colors = {d["label"]: d["color"] for d in chart_data}
    assert colors["TP TP84"] == CHART_COLORS[0]
    assert colors["LX LX1234"] == CHART_COLORS[1]
    assert colors["AF AF123"] == CHART_COLORS[2]


# --- the chart history series is per-flight too (plan 017 task 1.10) ---
# history_by_key is built by appending one point per get_price_history row, so
# a flight quoted by two sources in one snapshot produces two points at the
# SAME timestamp -- the line draws a vertical segment at every such snapshot.
# The same feed backs window.allFlights[].data, so filters.js redraws inherit
# it. Found by probing the shipped Phase 1 code; the planning grep missed it.

async def _seed_dual_sourced_snapshot(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        _price_row(SHARED_KEY, "google_flights", 711.0),
        _price_row(SHARED_KEY, "kayak", 785.0),
    ])


def _series_for(chart_data, label):
    return next(d for d in chart_data if d["label"] == label)["data"]


@pytest.mark.asyncio
async def test_chart_series_has_one_point_per_snapshot_for_a_dual_sourced_flight(client):
    await _seed_dual_sourced_snapshot(client)

    response = await client.get("/trackers/1")
    chart_data = _extract_js_global(response.text, "chartData")
    assert chart_data is not None

    series = _series_for(chart_data, "TP TP84")
    timestamps = [p["x"] for p in series]
    assert len(timestamps) == len(set(timestamps)), f"duplicate x values: {series}"
    assert len(series) == 1


@pytest.mark.asyncio
async def test_chart_series_point_uses_cheapest_price_for_a_dual_sourced_flight(client):
    """Consistent with every other dedup site in phase 1: cheapest quote wins.
    get_price_history orders by searched_at with no price tiebreak, so row
    order alone must not be relied on to pick it."""
    await _seed_dual_sourced_snapshot(client)

    response = await client.get("/trackers/1")
    chart_data = _extract_js_global(response.text, "chartData")
    assert chart_data is not None

    series = _series_for(chart_data, "TP TP84")
    assert [p["y"] for p in series] == [711.0]
