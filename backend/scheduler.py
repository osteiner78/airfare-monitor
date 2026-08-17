import asyncio
import random
from dataclasses import asdict
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler: AsyncIOScheduler | None = None

# Matches the format sqlite's datetime('now') writes elsewhere in this schema.
_KAYAK_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _kayak_due(next_due_at: str | None, now: datetime) -> bool:
    if next_due_at is None:
        return True
    return now >= datetime.strptime(next_due_at, _KAYAK_TS_FORMAT)


def _jittered_kayak_interval_minutes(base_minutes: float) -> float:
    """Randomize base_minutes within +/-20%, floored at 1.

    Perfectly regular polling is exactly the pattern PerimeterX (Kayak's bot
    detection) is built to catch, so Kayak's cadence must never be a fixed
    interval.
    """
    jittered = base_minutes * random.uniform(0.8, 1.2)
    return max(1.0, jittered)


# The next-due time is computed from a base BELOW the tracker's own interval so
# that jitter's upper end still lands before the next tick. At the full
# interval the +/-20% overshoots half the time, and because the old code also
# measured from cycle *end* the overshoot compounded: Kayak ran on every other
# tick (~6h instead of ~3h). Measured 2026-08-10/11 on tracker 20:
#   07:42 ran -> next due ~10:42 -> 10:31 tick was 11 min early -> SKIPPED
#   13:39 ran -> next due ~16:39 -> 16:31 tick was  8 min early -> SKIPPED
# 0.7 leaves 101-151 min against a 180 min tick: always inside, with ~29 min
# of headroom so a slow cycle cannot reintroduce the skip even if the
# measurement point ever slips back toward cycle end. Being due early costs
# nothing -- the tick still gates the actual run, so the real cadence stays
# ~180 min. The unpredictability that matters for detection comes from the
# 0-15 min pre-render sleep, which is unchanged.
_KAYAK_DUE_MARGIN = 0.7

_kayak_render_lock: asyncio.Lock | None = None


def _get_kayak_render_lock() -> asyncio.Lock:
    """Serialize Kayak renders across ALL trackers.

    `max_instances=1` is per-job, so it stops one tracker overlapping itself
    but not two trackers overlapping each other -- and every render drives the
    same Chromium profile at `data/kayak-profile`, which is single-writer. With
    Kayak enabled on trackers 20/21/22, whose jobs fire within a second of each
    other, concurrent renders would fight over that lock directory.
    """
    global _kayak_render_lock
    if _kayak_render_lock is None:
        _kayak_render_lock = asyncio.Lock()
    return _kayak_render_lock


async def _log_source_error(event: str, source, tracker_id: int) -> None:
    """Log a source's own last_error, if it set one, at its own severity.

    Shared shape between the main get_sources() loop and the Kayak call --
    both getattr(source, "last_error", ...) -> insert_log blocks were
    identical apart from the event name.
    """
    from backend.db import insert_log

    last_error = getattr(source, "last_error", None)
    if last_error:
        level = getattr(source, "last_error_level", "ERROR")
        await insert_log(
            level,
            event,
            tracker_id=tracker_id,
            message=f"{type(source).__name__}: {last_error}",
        )


async def search_and_store(tracker_id: int, delay: bool) -> None:
    from backend.db import create_snapshot, get_tracker, insert_flight_prices, insert_log, update_tracker
    from backend.fingerprint import make_flight_key
    from backend.sources import get_sources
    from backend.sources.kayak import KayakSource

    tracker = await get_tracker(tracker_id)
    if not tracker:
        return

    if tracker["depart_date"] < datetime.now().date().isoformat():
        if tracker["active"]:
            await update_tracker(tracker_id, active=False)
            remove_tracker_job(tracker_id)
            await insert_log("INFO", "tracker_paused", tracker_id=tracker_id, message="depart date passed")
        return

    await insert_log("INFO", "search_start", tracker_id=tracker_id)

    sources = get_sources()
    results = []
    for source in sources:
        try:
            found = await source.search(
                tracker["origin"],
                tracker["destination"],
                tracker["depart_date"],
                tracker.get("return_date"),
                tracker["currency"],
                tracker["top_n"],
            )
            results.extend(found)
            await _log_source_error("search_error", source, tracker_id)
        except Exception as e:
            await insert_log("ERROR", "search_error", tracker_id=tracker_id, message=str(e))

    # .get(), not [] -- in Active dev the code is live the moment it is edited,
    # while the trackers ALTER TABLE is confirmation-gated, so new code always
    # runs against an un-migrated table for some window. A missing column must
    # mean "Kayak off", never a KeyError that kills the whole search.
    if tracker.get("kayak_enabled") and _kayak_due(tracker.get("kayak_next_due_at"), datetime.now()):
        # Captured BEFORE the sleep and the render: measuring the next due time
        # from cycle end pushed it later every cycle, which is half of what
        # made Kayak run only every other tick (see _KAYAK_DUE_MARGIN).
        kayak_cycle_started = datetime.now()
        try:
            if delay:
                await asyncio.sleep(random.uniform(0, 15 * 60))
            kayak_source = KayakSource()
            async with _get_kayak_render_lock():
                kayak_results = await kayak_source.search(
                    tracker["origin"],
                    tracker["destination"],
                    tracker["depart_date"],
                    tracker.get("return_date"),
                    tracker["currency"],
                    tracker["top_n"],
                )
            results.extend(kayak_results)
            await _log_source_error("kayak_search_error", kayak_source, tracker_id)
        except Exception as e:
            await insert_log("ERROR", "kayak_search_error", tracker_id=tracker_id, message=str(e))
        finally:
            next_due_at = kayak_cycle_started + timedelta(
                minutes=_jittered_kayak_interval_minutes(
                    tracker["interval_minutes"] * _KAYAK_DUE_MARGIN
                )
            )
            await update_tracker(tracker_id, kayak_next_due_at=next_due_at.strftime(_KAYAK_TS_FORMAT))

    snapshot = await create_snapshot(tracker_id, results_count=len(results))

    if results:
        prices = [{**asdict(r), "flight_key": make_flight_key(r)} for r in results]
        await insert_flight_prices(snapshot["id"], tracker_id, prices)

        await _evaluate_notifications(tracker_id, min(r.price for r in results))

    await insert_log("INFO", "search_done", tracker_id=tracker_id, message=f"{len(results)} results")


async def _evaluate_notifications(tracker_id: int, best_price: float) -> None:
    from backend.db import insert_log, insert_notification_log, list_notifications

    rules = await list_notifications(tracker_id)
    for rule in rules:
        triggered = False
        if rule["rule_type"] == "price_below" and best_price <= rule["threshold"]:
            triggered = True
        elif rule["rule_type"] == "price_above" and best_price >= rule["threshold"]:
            triggered = True

        if triggered:
            await insert_notification_log(rule["id"], tracker_id, best_price)
            await insert_log("INFO", "notification_triggered", tracker_id=tracker_id, message=f"price {best_price} triggered {rule['rule_type']} {rule['threshold']}")


def add_tracker_job(tracker_id: int, interval_minutes: int, run_immediately: bool = True) -> None:
    if scheduler is None:
        return
    from datetime import timedelta
    next_run = datetime.now() if run_immediately else datetime.now() + timedelta(minutes=interval_minutes)
    scheduler.add_job(
        search_and_store,
        "interval",
        minutes=interval_minutes,
        args=[tracker_id, True],
        id=f"tracker_{tracker_id}",
        next_run_time=next_run,
        replace_existing=True,
    )


def remove_tracker_job(tracker_id: int) -> None:
    if scheduler is None:
        return
    job_id = f"tracker_{tracker_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
