import json

import backend.scheduler
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.db import (
    create_tracker,
    delete_tracker,
    get_flight_prices_for_snapshot,
    get_latest_snapshot,
    get_previous_snapshot,
    get_price_history,
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


def _enrich_summaries(summaries: list) -> list:
    for s in summaries:
        delta = None
        best = s.get("best_price")
        prev = s.get("previous_best_price")
        if best is not None and prev is not None:
            if best < prev:
                delta = {"type": "down", "amount": round(prev - best, 2)}
            elif best > prev:
                delta = {"type": "up", "amount": round(best - prev, 2)}
            else:
                delta = {"type": "same"}
        s["price_delta"] = delta
    return summaries


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summaries = await get_tracker_summaries()
    summaries = _enrich_summaries(summaries)
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

    summaries = _enrich_summaries(await get_tracker_summaries())
    return _render("partials/tracker_list.html", {"request": request, "trackers": summaries})


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

    summaries = _enrich_summaries(await get_tracker_summaries())
    updated = next((s for s in summaries if s["id"] == tracker_id), None)
    if updated is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    return _render("partials/tracker_card.html", {"request": request, "tracker": updated})


async def _build_detail_context(tracker_id: int) -> dict:
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    latest = await get_latest_snapshot(tracker_id)
    previous = await get_previous_snapshot(tracker_id)

    current_flights = []
    previous_prices = {}

    if latest:
        current_flights = await get_flight_prices_for_snapshot(latest["id"])

    if previous:
        prev = await get_flight_prices_for_snapshot(previous["id"])
        previous_prices = {p["flight_key"]: p["price"] for p in prev}

    flights_with_delta = []
    for flight in current_flights:
        delta = None
        prev_price = previous_prices.get(flight["flight_key"])
        if prev_price is not None:
            if flight["price"] < prev_price:
                delta = {"type": "down", "amount": round(prev_price - flight["price"], 2)}
            elif flight["price"] > prev_price:
                delta = {"type": "up", "amount": round(flight["price"] - prev_price, 2)}
            else:
                delta = {"type": "same"}
        else:
            delta = {"type": "new"}
        flights_with_delta.append({"flight": flight, "delta": delta})

    for item in flights_with_delta:
        f = item["flight"]
        for key in ("departure_time", "arrival_time"):
            val = f.get(key)
            if val and "T" in str(val):
                date_part, time_part = str(val).split("T", 1)
                time_part = time_part.split("+")[0].split("-")[0].split("Z")[0]
                if len(time_part) >= 5:
                    time_part = time_part[:5]
                f[key + "_date"] = date_part
                f[key + "_time"] = time_part

    history = await get_price_history(tracker_id)

    chart_datasets = {}
    for row in history:
        key = row["flight_key"]
        if key not in chart_datasets:
            chart_datasets[key] = {
                "label": f"{row.get('airline', '') or ''} {row.get('flight_number', '') or ''}".strip(),
                "data": [],
            }
        chart_datasets[key]["data"].append({
            "x": row["searched_at"],
            "y": row["price"],
        })

    return {
        "tracker": tracker,
        "latest_snapshot": latest,
        "flights_with_delta": flights_with_delta,
        "chart_datasets": json.dumps(list(chart_datasets.values())),
    }


@router.get("/trackers/{tracker_id}", response_class=HTMLResponse)
async def tracker_detail(request: Request, tracker_id: int):
    ctx = await _build_detail_context(tracker_id)
    ctx["request"] = request
    return _render("tracker.html", ctx)


@router.post("/trackers/{tracker_id}/search", response_class=HTMLResponse)
async def search_now(request: Request, tracker_id: int):
    await backend.scheduler.search_and_store(tracker_id)
    ctx = await _build_detail_context(tracker_id)
    ctx["request"] = request
    return _render("partials/detail_content.html", ctx)


@router.delete("/trackers/{tracker_id}", response_class=HTMLResponse)
async def delete_tracker_card(request: Request, tracker_id: int):
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)

    summaries = _enrich_summaries(await get_tracker_summaries())
    return _render("partials/tracker_list.html", {"request": request, "trackers": summaries})


@router.patch("/trackers/{tracker_id}/toggle-detail", response_class=HTMLResponse)
async def toggle_tracker_detail(request: Request, tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    new_active = not tracker["active"]
    await update_tracker(tracker_id, active=new_active)

    if new_active:
        backend.scheduler.add_tracker_job(tracker_id, tracker["interval_minutes"])
    else:
        backend.scheduler.remove_tracker_job(tracker_id)

    ctx = await _build_detail_context(tracker_id)
    ctx["request"] = request
    return _render("partials/detail_content.html", ctx)


@router.delete("/trackers/{tracker_id}/detail", response_class=HTMLResponse)
async def delete_tracker_detail(request: Request, tracker_id: int):
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/"
    return response
