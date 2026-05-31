import backend.scheduler
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.db import (
    create_tracker,
    delete_tracker,
    get_tracker,
    get_tracker_summaries,
    update_tracker,
)

_env = Environment(
    loader=FileSystemLoader("frontend/templates"),
    autoescape=select_autoescape(),
    cache_size=0,
)

router = APIRouter()


def _render(name: str, context: dict) -> HTMLResponse:
    template = _env.get_template(name)
    return HTMLResponse(template.render(context))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summaries = await get_tracker_summaries()
    return _render("dashboard.html", {"request": request, "trackers": summaries})


@router.post("/", response_class=HTMLResponse)
async def add_tracker(request: Request):
    form = await request.form()
    tracker = await create_tracker(
        origin=form["origin"],
        destination=form["destination"],
        depart_date=form["depart_date"],
        return_date=form.get("return_date") or None,
    )
    backend.scheduler.add_tracker_job(tracker["id"], tracker["interval_minutes"])

    summaries = await get_tracker_summaries()
    return _render("dashboard.html", {"request": request, "trackers": summaries})


@router.patch("/trackers/{tracker_id}/toggle", response_class=HTMLResponse)
async def toggle_tracker(request: Request, tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    new_active = not tracker["active"]
    await update_tracker(tracker_id, active=new_active)

    if new_active:
        backend.scheduler.add_tracker_job(tracker_id, tracker["interval_minutes"])
    else:
        backend.scheduler.remove_tracker_job(tracker_id)

    summaries = await get_tracker_summaries()
    updated = next((s for s in summaries if s["id"] == tracker_id), None)
    if updated is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    return _render("partials/tracker_card.html", {"request": request, "tracker": updated})


@router.delete("/trackers/{tracker_id}", response_class=HTMLResponse)
async def delete_tracker_card(request: Request, tracker_id: int):
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)

    summaries = await get_tracker_summaries()
    return _render("dashboard.html", {"request": request, "trackers": summaries})
