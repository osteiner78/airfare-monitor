import pytest


@pytest.mark.asyncio
async def test_get_historical_best_price_returns_min_for_tracker_with_data(db_path):
    from backend.db import create_snapshot, create_tracker, get_historical_best_price, insert_flight_prices

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    snapshot = await create_snapshot(tracker["id"], results_count=3)
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": "test|XX|1|2026-01-01T00:00:00", "source": "test", "price": 100.0, "currency": "EUR"},
        {"flight_key": "test|XX|2|2026-01-01T00:00:00", "source": "test", "price": 50.0, "currency": "EUR"},
        {"flight_key": "test|XX|3|2026-01-01T00:00:00", "source": "test", "price": 150.0, "currency": "EUR"},
    ])

    result = await get_historical_best_price(tracker["id"])
    assert result == 50.0


@pytest.mark.asyncio
async def test_get_historical_best_price_returns_none_for_tracker_with_no_data(db_path):
    from backend.db import create_tracker, get_historical_best_price

    tracker = await create_tracker(origin="GVA", destination="BCN", depart_date="2026-09-15")
    result = await get_historical_best_price(tracker["id"])
    assert result is None


@pytest.mark.asyncio
async def test_get_historical_best_price_returns_none_for_nonexistent_tracker(db_path):
    from backend.db import get_historical_best_price

    result = await get_historical_best_price(999)
    assert result is None
