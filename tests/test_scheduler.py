"""Tests for plan 027 Phase 3 -- scheduler hygiene (#6, #7).

#7: the price row dict inside search_and_store used to hand-spell all eleven
of FlightResult's fields by name, plus flight_key. A new field added to the
dataclass with no matching key in that dict would silently never reach the
database -- nothing errors, the value is just gone. The row is now built
generically as `{**asdict(r), "flight_key": make_flight_key(r)}`, and the
test below proves the guarantee by walking `dataclasses.fields(FlightResult)`
itself rather than naming any field -- so a future field is covered without
touching this test.

#6: `search_and_store`'s `delay: bool = True` default let a caller silently
forget to pass delay=False (every current call site already does, but the
default was the trap, not any specific caller). The default is gone; every
call site -- including the APScheduler registration in add_tracker_job, now
passing delay=True explicitly -- states it.
"""

import dataclasses

from unittest.mock import AsyncMock, patch

TRACKER = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}


def _flight(**overrides) -> "object":
    from backend.sources.base import FlightResult

    fields = dict(
        source="google_flights",
        price=711.0,
        currency="EUR",
        duration_min=1305,
        stops=1,
        airline="TAP AIR PORTUGAL",
        flight_number="TP 88",
        departure_time="2026-08-21T00:45:00",
        arrival_time="2026-08-21T22:30:00",
        legs_json="[]",
        booking_url="https://example.test/itinerary",
    )
    fields.update(overrides)
    return FlightResult(**fields)


class _FakeSource:
    def __init__(self, results):
        self._results = results
        self.last_error = None
        self.last_error_level = "ERROR"

    async def search(self, *args, **kwargs):
        return list(self._results)


async def test_every_flight_result_field_reaches_the_stored_row(db_path):
    """Walks FlightResult's own fields rather than naming them, so this test
    covers a field added to the dataclass tomorrow without being edited --
    the guarantee a hand-spelled dict can never give."""
    from backend.db import create_tracker, get_flight_prices_for_snapshot, get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker = await create_tracker(**TRACKER)
    result = _flight()

    with patch("backend.sources.get_sources", lambda: [_FakeSource([result])]), \
         patch("backend.sources.kayak.KayakSource.search", AsyncMock(return_value=[])):
        await search_and_store(tracker["id"], delay=False)

    snapshot = await get_latest_snapshot(tracker["id"])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert len(rows) == 1
    row = rows[0]

    for field in dataclasses.fields(result):
        assert row[field.name] == getattr(result, field.name), field.name


async def test_search_and_store_has_no_delay_default():
    """The trap #6 describes was the default itself, not any one caller --
    removing it means a new call site can't silently inherit delay=True."""
    import inspect

    from backend.scheduler import search_and_store

    delay_param = inspect.signature(search_and_store).parameters["delay"]
    assert delay_param.default is inspect.Parameter.empty


def test_add_tracker_job_passes_delay_explicitly():
    """The APScheduler registration was the one call site that relied on the
    old default (args=[tracker_id], not args=[tracker_id, True]) -- confirm
    a real scheduled tick still gets its pre-render jitter sleep."""
    from unittest.mock import MagicMock

    import backend.scheduler as scheduler

    fake_scheduler = MagicMock()
    with patch.object(scheduler, "scheduler", fake_scheduler):
        scheduler.add_tracker_job(1, 60)

    _args, kwargs = fake_scheduler.add_job.call_args
    assert kwargs["args"] == [1, True]
