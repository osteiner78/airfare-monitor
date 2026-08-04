import pytest

TRACKER_FORM = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}


@pytest.mark.asyncio
async def test_get_tracker_summaries_best_source_matches_cheapest_price_row(db_path):
    from backend.db import create_snapshot, create_tracker, get_tracker_summaries, insert_flight_prices

    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-08-21")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "kayak", "price": 785.0, "currency": "EUR"},
        {"flight_key": "TP|TP88|2026-08-21T20:45:00", "source": "google_flights", "price": 711.0, "currency": "EUR"},
    ])

    summaries = await get_tracker_summaries()
    summary = next(s for s in summaries if s["id"] == tracker["id"])
    assert summary["best_price"] == 711.0
    assert summary["best_source"] == "google_flights"


@pytest.mark.asyncio
async def test_get_tracker_summaries_best_source_updates_when_a_cheaper_source_appears(db_path):
    from backend.db import create_snapshot, create_tracker, get_tracker_summaries, insert_flight_prices

    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-08-21")
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "TP|TP88|2026-08-21T20:45:00", "source": "google_flights", "price": 711.0, "currency": "EUR"},
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "kayak", "price": 650.0, "currency": "EUR"},
    ])

    summaries = await get_tracker_summaries()
    summary = next(s for s in summaries if s["id"] == tracker["id"])
    assert summary["best_price"] == 650.0
    assert summary["best_source"] == "kayak"


@pytest.mark.asyncio
async def test_get_tracker_summaries_best_source_is_none_when_no_snapshots(db_path):
    from backend.db import create_tracker, get_tracker_summaries

    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-08-21")
    summaries = await get_tracker_summaries()
    summary = next(s for s in summaries if s["id"] == tracker["id"])
    assert summary["best_source"] is None


@pytest.mark.asyncio
async def test_best_source_is_deterministic_when_two_sources_tie_on_price(db_path):
    """With sources sharing a snapshot, two of them quoting the same flight at
    the same price is the EXPECTED case, not an edge case. A bare
    `ORDER BY price ASC LIMIT 1` picks arbitrarily, so attribution would flip
    between identical runs. Pinned to the alphabetically-first source."""
    from backend.db import create_snapshot, create_tracker, get_tracker_summaries, insert_flight_prices

    rows = [
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "kayak", "price": 711.0, "currency": "EUR"},
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "google_flights", "price": 711.0, "currency": "EUR"},
    ]

    # Same tie, opposite insertion order -> must yield the same attribution.
    answers = []
    for order in (rows, list(reversed(rows))):
        tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-08-21")
        snapshot = await create_snapshot(tracker["id"], results_count=2)
        await insert_flight_prices(snapshot["id"], tracker["id"], order)
        summaries = await get_tracker_summaries()
        answers.append(next(s for s in summaries if s["id"] == tracker["id"])["best_source"])

    assert answers[0] == answers[1] == "google_flights"


@pytest.mark.asyncio
async def test_results_table_shows_source_for_each_flight_row(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        {"flight_key": "TP|TP88|2026-08-21T20:45:00", "source": "google_flights", "price": 711.0,
         "currency": "EUR", "airline": "TP", "flight_number": "TP88",
         "departure_time": "2026-08-21T20:45:00", "arrival_time": "2026-08-21T22:30:00",
         "duration_min": 105, "stops": 0},
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "kayak", "price": 785.0,
         "currency": "EUR", "airline": "TP", "flight_number": "TP84",
         "departure_time": "2026-08-21T00:45:00", "arrival_time": "2026-08-21T22:30:00",
         "duration_min": 1305, "stops": 1},
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "Kayak" in response.text
    assert "Google Flights" in response.text


@pytest.mark.asyncio
async def test_results_table_source_label_falls_back_to_raw_value_for_unknown_source(client):
    from backend.db import create_snapshot, insert_flight_prices

    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [
        {"flight_key": "TP|TP84|2026-08-21T00:45:00", "source": "some_future_source", "price": 100.0,
         "currency": "EUR", "airline": "TP", "flight_number": "TP84",
         "departure_time": "2026-08-21T00:45:00", "arrival_time": "2026-08-21T22:30:00",
         "duration_min": 105, "stops": 0},
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "some_future_source" in response.text
