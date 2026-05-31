from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler: AsyncIOScheduler | None = None


async def search_and_store(tracker_id: int) -> None:
    from backend.db import create_snapshot, get_tracker, insert_flight_prices
    from backend.fingerprint import make_flight_key
    from backend.sources import get_sources

    tracker = await get_tracker(tracker_id)
    if not tracker:
        return

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
        except Exception:
            pass

    snapshot = await create_snapshot(tracker_id, results_count=len(results))

    if results:
        prices = [
            {
                "flight_key": make_flight_key(r),
                "source": r.source,
                "price": r.price,
                "currency": r.currency,
                "duration_min": r.duration_min,
                "stops": r.stops,
                "airline": r.airline,
                "flight_number": r.flight_number,
                "departure_time": r.departure_time,
                "arrival_time": r.arrival_time,
                "legs_json": r.legs_json,
                "booking_url": r.booking_url,
            }
            for r in results
        ]
        await insert_flight_prices(snapshot["id"], tracker_id, prices)

        await _evaluate_notifications(tracker_id, min(r.price for r in results))


async def _evaluate_notifications(tracker_id: int, best_price: float) -> None:
    from backend.db import insert_notification_log, list_notifications

    rules = await list_notifications(tracker_id)
    for rule in rules:
        triggered = False
        if rule["rule_type"] == "price_below" and best_price <= rule["threshold"]:
            triggered = True
        elif rule["rule_type"] == "price_above" and best_price >= rule["threshold"]:
            triggered = True

        if triggered:
            await insert_notification_log(rule["id"], tracker_id, best_price)


def add_tracker_job(tracker_id: int, interval_minutes: int) -> None:
    if scheduler is None:
        return
    scheduler.add_job(
        search_and_store,
        "interval",
        minutes=interval_minutes,
        args=[tracker_id],
        id=f"tracker_{tracker_id}",
        next_run_time=datetime.now(),
        replace_existing=True,
    )


def remove_tracker_job(tracker_id: int) -> None:
    if scheduler is None:
        return
    job_id = f"tracker_{tracker_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
