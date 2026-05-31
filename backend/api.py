import backend.scheduler
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.db import (
    create_notification,
    create_tracker,
    delete_notification,
    delete_tracker,
    get_notification,
    get_price_history,
    get_tracker,
    get_tracker_summaries,
    list_notifications,
    update_tracker,
)
from backend.models import (
    NotificationCreate,
    NotificationResponse,
    TrackerCreate,
    TrackerResponse,
    TrackerUpdate,
)

router = APIRouter(prefix="/api")


@router.get("/trackers")
async def list_trackers_endpoint():
    return await get_tracker_summaries()


@router.post("/trackers", status_code=201)
async def create_tracker_endpoint(payload: TrackerCreate) -> TrackerResponse:
    tracker = await create_tracker(**payload.model_dump(exclude_none=True))
    backend.scheduler.add_tracker_job(tracker["id"], tracker["interval_minutes"])
    return TrackerResponse(**tracker)


@router.get("/trackers/{tracker_id}")
async def get_tracker_endpoint(tracker_id: int) -> TrackerResponse:
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return TrackerResponse(**tracker)


@router.patch("/trackers/{tracker_id}")
async def update_tracker_endpoint(tracker_id: int, payload: TrackerUpdate) -> TrackerResponse:
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    updates = payload.model_dump(exclude_none=True)
    tracker = await update_tracker(tracker_id, **updates)

    active = updates.get("active")
    if active is True:
        backend.scheduler.add_tracker_job(tracker_id, tracker["interval_minutes"])
    elif active is False:
        backend.scheduler.remove_tracker_job(tracker_id)

    return TrackerResponse(**tracker)


@router.delete("/trackers/{tracker_id}", status_code=204)
async def delete_tracker_endpoint(tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)
    return Response(status_code=204)


@router.get("/trackers/{tracker_id}/history")
async def get_history_endpoint(tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    history = await get_price_history(tracker_id)

    best_by_time = {}
    for row in history:
        t = row["searched_at"]
        p = row["price"]
        if t not in best_by_time or p < best_by_time[t]:
            best_by_time[t] = p

    best_prices = [{"x": t, "y": p} for t, p in sorted(best_by_time.items())]
    return {"flights": history, "best_prices": best_prices}


@router.post("/trackers/{tracker_id}/search")
async def search_now_endpoint(tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    await backend.scheduler.search_and_store(tracker_id)
    return {"status": "ok"}


@router.post("/notifications", status_code=201)
async def create_notification_endpoint(payload: NotificationCreate) -> NotificationResponse:
    tracker = await get_tracker(payload.tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    notification = await create_notification(
        tracker_id=payload.tracker_id,
        rule_type=payload.rule_type,
        threshold=payload.threshold,
    )
    return NotificationResponse(**notification)


@router.get("/trackers/{tracker_id}/notifications")
async def list_notifications_endpoint(tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return await list_notifications(tracker_id)


@router.delete("/notifications/{notification_id}", status_code=204)
async def delete_notification_endpoint(notification_id: int):
    notification = await get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    await delete_notification(notification_id)
    return Response(status_code=204)
