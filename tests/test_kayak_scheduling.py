"""Tests for plan 017 phase 3 — Kayak wired into the main search cycle.

REVISED for plan 017 v2. The first version of this file tested a design that
has been withdrawn: a separate `kayak_search_and_store` coroutine on its own
APScheduler job (`kayak_{id}`) writing its own snapshots. That gave Kayak
*partial* snapshots, which every "latest snapshot" consumer in the codebase
(`get_tracker_summaries.best_price`, `previous_best_price`,
`get_best_price_series`, `_build_detail_context`'s missing/new diff,
`_evaluate_notifications`) silently misreads as a complete view of the
market. See the "Why Kayak shares the main snapshot" section of the plan.

The design under test now: `search_and_store` makes one extra, conditional
Kayak call — gated by `trackers.kayak_enabled` and a persisted
`trackers.kayak_next_due_at` due-check — and Kayak's results join the same
`results` list, the same snapshot, and the same notification evaluation as
fli's. A Kayak failure degrades to "zero extra rows", exactly as a
FallbackSource failure already does.

Dropped from v1 (the functions no longer exist): the seven
`kayak_search_and_store` tests and the three `add_kayak_job`/
`remove_kayak_job` tests. Kept unchanged: the two `kayak_enabled` column
tests and the three jitter tests.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.
  NON-REGRESSION               -> must already pass against current code.

Everything here is NEW-BEHAVIOR or FAILURE-MODE: before phase 3 these fail
with ModuleNotFoundError (`backend.sources.kayak`), AttributeError
(`_kayak_due`, `_jittered_kayak_interval_minutes`) or KeyError
(`kayak_enabled`, `kayak_next_due_at`).
"""

import os
from datetime import datetime, timedelta

import aiosqlite
import pytest
from unittest.mock import AsyncMock, patch

TRACKER = {"origin": "GRU", "destination": "ZRH", "depart_date": "2026-08-21"}

# Matches the format sqlite's datetime('now') writes elsewhere in this schema
# (snapshots.searched_at, trackers.created_at). The implementation of
# _kayak_due must parse this.
_TS = "%Y-%m-%d %H:%M:%S"


def _ts(dt: datetime) -> str:
    return dt.strftime(_TS)


def _flight(source: str, price: float, flight_number: str = "TP 84") -> "object":
    from backend.sources.base import FlightResult
    return FlightResult(
        source=source,
        price=price,
        currency="EUR",
        duration_min=1305,
        stops=1,
        airline="TAP AIR PORTUGAL",
        flight_number=flight_number,
        departure_time="2026-08-21T00:45:00",
        arrival_time="2026-08-21T22:30:00",
        legs_json="[]",
        booking_url="https://example.test/itinerary",
    )


class _FakeSource:
    """Stands in for FallbackSource in get_sources()."""

    def __init__(self, results=None):
        self._results = results or []
        self.last_error = None
        self.last_error_level = "ERROR"

    async def search(self, *args, **kwargs):
        return list(self._results)


def _fli_returning(*results):
    return patch("backend.sources.get_sources", lambda: [_FakeSource(list(results))])


async def _kayak_blocked(self, *args, **kwargs):
    """A Kayak run that hits bot detection: empty list + WARNING, never raises."""
    self.last_error = "blocked: bot detection markers present"
    self.last_error_level = "WARNING"
    return []


async def _snapshot_count(tracker_id: int) -> int:
    async with aiosqlite.connect(os.environ["AIRFARE_DB_PATH"]) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM snapshots WHERE tracker_id = ?", (tracker_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0]


async def _due_tracker(**overrides):
    """A tracker that is opted in to Kayak and due for a check right now."""
    from backend.db import create_tracker, update_tracker
    tracker = await create_tracker(**TRACKER)
    fields = {"kayak_enabled": 1, "kayak_next_due_at": _ts(datetime.now() - timedelta(hours=1))}
    fields.update(overrides)
    await update_tracker(tracker["id"], **fields)
    return tracker["id"]


# --- schema: the two new trackers columns ---

async def test_create_tracker_defaults_kayak_enabled_to_false(db_path):
    from backend.db import create_tracker
    tracker = await create_tracker(**TRACKER)
    assert not tracker["kayak_enabled"]


async def test_tracker_kayak_enabled_can_be_turned_on(db_path):
    from backend.db import create_tracker, update_tracker
    tracker = await create_tracker(**TRACKER)
    updated = await update_tracker(tracker["id"], kayak_enabled=1)
    assert updated["kayak_enabled"]


async def test_kayak_next_due_at_defaults_to_null(db_path):
    """NULL means 'never attempted', which _kayak_due reads as due now -- so a
    freshly opted-in tracker gets checked on its next main tick rather than
    waiting a full interval."""
    from backend.db import create_tracker
    tracker = await create_tracker(**TRACKER)
    assert tracker["kayak_next_due_at"] is None


# --- the due-check (pure) ---

def test_kayak_due_when_next_due_at_is_null():
    from backend.scheduler import _kayak_due
    assert _kayak_due(None, datetime.now()) is True


def test_kayak_due_when_now_is_past_next_due_at():
    from backend.scheduler import _kayak_due
    now = datetime.now()
    assert _kayak_due(_ts(now - timedelta(minutes=1)), now) is True


def test_kayak_not_due_when_now_is_before_next_due_at():
    from backend.scheduler import _kayak_due
    now = datetime.now()
    assert _kayak_due(_ts(now + timedelta(hours=2)), now) is False


# --- the jitter (pure) ---

def test_jittered_kayak_interval_stays_within_documented_bounds():
    from backend.scheduler import _jittered_kayak_interval_minutes
    base = 180
    samples = [_jittered_kayak_interval_minutes(base) for _ in range(50)]
    assert all(base * 0.8 <= s <= base * 1.2 for s in samples)


def test_jittered_kayak_interval_is_not_always_the_same_value():
    from backend.scheduler import _jittered_kayak_interval_minutes
    samples = {_jittered_kayak_interval_minutes(180) for _ in range(50)}
    assert len(samples) > 1


def test_jittered_kayak_interval_handles_small_base_without_going_non_positive():
    from backend.scheduler import _jittered_kayak_interval_minutes
    for _ in range(50):
        assert _jittered_kayak_interval_minutes(1) >= 1


# --- the core of this phase: one snapshot, all sources ---

async def test_search_and_store_puts_kayak_and_fli_results_in_the_same_snapshot(db_path):
    """THE assertion this phase exists for. Kayak must not create a snapshot of
    its own -- a snapshot is the unit of 'the whole market at time T', and a
    Kayak-only snapshot is a partial view that best_price, the trend chip, the
    sparkline and the missing/new diff all misread as complete."""
    from backend.db import get_flight_prices_for_snapshot, get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search",
               AsyncMock(return_value=[_flight("kayak", 785.0, "TP 84")])):
        await search_and_store(tracker_id, delay=False)

    assert await _snapshot_count(tracker_id) == 1
    snapshot = await get_latest_snapshot(tracker_id)
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert {r["source"] for r in rows} == {"google_flights", "kayak"}


async def test_snapshot_results_count_includes_both_sources(db_path):
    from backend.db import get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search",
               AsyncMock(return_value=[_flight("kayak", 785.0, "TP 84")])):
        await search_and_store(tracker_id, delay=False)

    snapshot = await get_latest_snapshot(tracker_id)
    assert snapshot["results_count"] == 2


async def test_notifications_evaluate_against_cross_source_minimum_price(db_path):
    """fli quotes 900, Kayak quotes 785, the rule fires below 800. The alert
    must fire -- which only works if both sources' prices reach the same
    _evaluate_notifications call."""
    from backend.db import create_notification, get_recent_alerts_count
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()
    await create_notification(tracker_id, "price_below", 800.0)

    with _fli_returning(_flight("google_flights", 900.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search",
               AsyncMock(return_value=[_flight("kayak", 785.0, "TP 84")])):
        await search_and_store(tracker_id, delay=False)

    assert await get_recent_alerts_count(tracker_id) == 1


# --- the opt-in and cadence gates ---

async def test_search_and_store_does_not_call_kayak_when_kayak_disabled(db_path):
    from backend.db import create_tracker
    from backend.scheduler import search_and_store

    tracker = await create_tracker(**TRACKER)  # kayak_enabled left at its default (0)
    kayak_mock = AsyncMock(return_value=[_flight("kayak", 785.0)])

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search", kayak_mock):
        await search_and_store(tracker["id"], delay=False)

    kayak_mock.assert_not_called()


async def test_search_and_store_does_not_call_kayak_when_not_due(db_path):
    """Kayak's cadence is its own: enabled but not yet due must skip the call
    entirely -- no browser launch, no LLM spend -- while the main sources run
    normally."""
    from backend.db import get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker(
        kayak_next_due_at=_ts(datetime.now() + timedelta(hours=2))
    )
    kayak_mock = AsyncMock(return_value=[_flight("kayak", 785.0)])

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search", kayak_mock):
        await search_and_store(tracker_id, delay=False)

    kayak_mock.assert_not_called()
    snapshot = await get_latest_snapshot(tracker_id)
    assert snapshot["results_count"] == 1  # fli still ran


async def test_search_and_store_advances_next_due_at_after_a_successful_kayak_run(db_path):
    from backend.db import get_tracker
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search",
               AsyncMock(return_value=[_flight("kayak", 785.0, "TP 84")])):
        await search_and_store(tracker_id, delay=False)

    tracker = await get_tracker(tracker_id)
    assert tracker["kayak_next_due_at"] is not None
    assert datetime.strptime(tracker["kayak_next_due_at"], _TS) > datetime.now()


async def test_search_and_store_advances_next_due_at_after_a_failed_kayak_run(db_path):
    """A blocked run must still push the due time forward. Otherwise a tracker
    that Kayak is blocking retries on every single main tick, which is exactly
    the hammering pattern that gets the IP blocked harder."""
    from backend.db import get_tracker
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search", _kayak_blocked):
        await search_and_store(tracker_id, delay=False)

    tracker = await get_tracker(tracker_id)
    assert tracker["kayak_next_due_at"] is not None
    assert datetime.strptime(tracker["kayak_next_due_at"], _TS) > datetime.now()


# --- graceful degradation: Kayak failing must not damage the main path ---

async def test_kayak_failure_still_stores_fli_results_and_creates_snapshot(db_path):
    """The whole reason Kayak shares the main snapshot: at ~40-70% success it
    fails often, and a failure must be indistinguishable from 'Kayak simply
    wasn't due' as far as the stored data is concerned."""
    from backend.db import get_flight_prices_for_snapshot, get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search", _kayak_blocked):
        await search_and_store(tracker_id, delay=False)

    snapshot = await get_latest_snapshot(tracker_id)
    assert snapshot is not None
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert [r["price"] for r in rows] == [711.0]


async def test_kayak_failure_logs_kayak_search_error_at_its_own_level(db_path):
    """Distinct event name from the main loop's `search_error` so /monitor can
    separate 'Kayak got blocked again' from 'Google Flights broke'."""
    from backend.db import get_recent_logs
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search", _kayak_blocked):
        await search_and_store(tracker_id, delay=False)

    logs = await get_recent_logs(limit=20)
    assert any(
        log["event"] == "kayak_search_error" and log["level"] == "WARNING"
        for log in logs
    )


async def test_search_and_store_survives_tracker_row_without_kayak_columns(db_path):
    """Active dev deploys code the instant it is edited, but the trackers
    ALTER TABLE is confirmation-gated -- so there is always a window where the
    new code runs against an un-migrated table. A missing column must degrade
    to 'Kayak off', not raise KeyError out of search_and_store and kill every
    tracker's search. Observed live on 2026-08-04: 28 consecutive job failures,
    all price collection stalled."""
    from backend.db import create_tracker, get_latest_snapshot, get_tracker
    from backend.scheduler import search_and_store

    tracker = await create_tracker(**TRACKER)
    unmigrated = {k: v for k, v in (await get_tracker(tracker["id"])).items()
                  if k not in ("kayak_enabled", "kayak_next_due_at")}

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.db.get_tracker", AsyncMock(return_value=unmigrated)):
        await search_and_store(tracker["id"], delay=False)  # must not raise

    snapshot = await get_latest_snapshot(tracker["id"])
    assert snapshot is not None
    assert snapshot["results_count"] == 1


async def test_kayak_exception_never_propagates_out_of_search_and_store(db_path):
    """KayakSource.search is contractually never-raises, but search_and_store
    must not depend on that contract holding -- an escaping exception would
    kill the snapshot and lose fli's perfectly good results."""
    from backend.db import get_latest_snapshot
    from backend.scheduler import search_and_store

    tracker_id = await _due_tracker()

    with _fli_returning(_flight("google_flights", 711.0, "TP 88")), \
         patch("backend.sources.kayak.KayakSource.search",
               AsyncMock(side_effect=RuntimeError("playwright died"))):
        await search_and_store(tracker_id, delay=False)  # must not raise

    snapshot = await get_latest_snapshot(tracker_id)
    assert snapshot is not None
    assert snapshot["results_count"] == 1


# --- the detail-page kayak toggle (3.8), added during implementation ---

async def test_toggle_kayak_endpoint_flips_kayak_enabled(client):
    from backend.db import get_tracker

    await client.post("/api/trackers", json=TRACKER)
    response = await client.patch("/trackers/1/toggle-kayak")
    assert response.status_code == 200

    tracker = await get_tracker(1)
    assert tracker["kayak_enabled"]


async def test_toggle_kayak_endpoint_returns_404_for_missing_tracker(client):
    response = await client.patch("/trackers/999/toggle-kayak")
    assert response.status_code == 404


async def test_toggle_kayak_endpoint_survives_tracker_row_without_kayak_column(client):
    """Same un-migrated-table window as search_and_store: a bracket read of
    tracker["kayak_enabled"] would KeyError instead of degrading to 'off'."""
    from backend.db import get_tracker

    await client.post("/api/trackers", json=TRACKER)
    tracker = await get_tracker(1)
    unmigrated = {k: v for k, v in tracker.items() if k != "kayak_enabled"}

    with patch("backend.pages.get_tracker", AsyncMock(return_value=unmigrated)):
        response = await client.patch("/trackers/1/toggle-kayak")  # must not raise

    assert response.status_code == 200
