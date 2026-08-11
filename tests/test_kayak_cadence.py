"""Kayak cadence and render serialization.

Two defects found on live data 2026-08-11, both added here as regression tests.

1. EVERY-OTHER-CYCLE DRIFT. `kayak_next_due_at` was measured from cycle *end*
   and jittered around the FULL tracker interval, so it landed after the next
   tick roughly half the time -- and because cycle end drifts later than cycle
   start, the miss compounded. Observed on tracker 20:
       07:42 ran -> next due ~10:42 -> 10:31 tick 11 min early -> SKIPPED
       13:39 ran -> next due ~16:39 -> 16:31 tick  8 min early -> SKIPPED
   Kayak therefore refreshed every ~6h against a 3h tracker.

2. CROSS-TRACKER CONCURRENCY. `max_instances=1` is per-job. With Kayak enabled
   on trackers 20/21/22, whose jobs fire within a second of each other, two
   renders could drive the single-writer Chromium profile at
   `data/kayak-profile` simultaneously.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from backend.scheduler import (
    _KAYAK_DUE_MARGIN,
    _get_kayak_render_lock,
    _jittered_kayak_interval_minutes,
    _kayak_due,
)

_TS = "%Y-%m-%d %H:%M:%S"


# --- 1. the drift ---

def test_next_due_always_lands_before_the_following_tick():
    """The property that was violated. Whatever the jitter rolls, the next due
    time must fall inside the tracker's own interval, or a tick gets skipped."""
    interval = 180
    for _ in range(500):
        gap = _jittered_kayak_interval_minutes(interval * _KAYAK_DUE_MARGIN)
        assert gap < interval, (
            f"next-due gap {gap:.1f} min >= tick interval {interval} min -- "
            "this is the every-other-cycle skip"
        )


def test_next_due_is_still_irregular():
    """The margin must not turn the cadence into a fixed interval -- regular
    polling is what PerimeterX is built to catch."""
    samples = {
        round(_jittered_kayak_interval_minutes(180 * _KAYAK_DUE_MARGIN), 3)
        for _ in range(50)
    }
    assert len(samples) > 10


def test_next_due_is_not_absurdly_early():
    """Guard the other direction: the margin rate-limits Kayak, so it must not
    collapse toward running on every search."""
    for _ in range(200):
        assert _jittered_kayak_interval_minutes(180 * _KAYAK_DUE_MARGIN) > 90


def test_a_tick_one_interval_later_is_due_with_the_new_margin():
    """End to end on the real numbers: run at T, tick at T+180, must be due."""
    ran_at = datetime(2026, 8, 11, 7, 42, 0)
    for _ in range(200):
        gap = _jittered_kayak_interval_minutes(180 * _KAYAK_DUE_MARGIN)
        next_due = (ran_at + timedelta(minutes=gap)).strftime(_TS)
        assert _kayak_due(next_due, ran_at + timedelta(minutes=180))


def test_measuring_from_cycle_end_would_still_be_safe_within_the_margin():
    """A slow cycle (jitter sleep + render + LLM) can add ~20 min. Even if the
    measurement point slipped that far, the margin must absorb it."""
    worst_case_cycle_minutes = 20
    for _ in range(200):
        gap = _jittered_kayak_interval_minutes(180 * _KAYAK_DUE_MARGIN)
        assert gap + worst_case_cycle_minutes < 180


# --- 2. the lock ---

async def test_kayak_render_lock_is_shared_across_callers():
    """One lock for the whole process, not one per tracker -- a per-tracker
    lock would not prevent the collision it exists to prevent."""
    assert _get_kayak_render_lock() is _get_kayak_render_lock()


async def test_kayak_render_lock_serializes_two_concurrent_renders():
    """Two trackers rendering at once must not overlap: the Chromium profile
    directory is single-writer."""
    overlapping = False
    active = 0

    async def fake_render():
        nonlocal overlapping, active
        async with _get_kayak_render_lock():
            active += 1
            if active > 1:
                overlapping = True
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(fake_render() for _ in range(4)))
    assert not overlapping, "two Kayak renders held the profile at the same time"


async def test_kayak_render_lock_is_released_when_a_render_raises():
    """KayakSource.search is contract-bound never to raise, but the scheduler
    catches defensively -- so the lock must survive an exception either way,
    or one failure would wedge Kayak for every tracker until restart."""
    with pytest.raises(RuntimeError):
        async with _get_kayak_render_lock():
            raise RuntimeError("render blew up")

    await asyncio.wait_for(_get_kayak_render_lock().acquire(), timeout=0.5)
    _get_kayak_render_lock().release()
