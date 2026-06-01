import json
import re
from datetime import datetime

import backend.scheduler
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.db import (
    create_tracker,
    delete_tracker,
    get_db_stats,
    get_flight_prices_for_snapshot,
    get_historical_best_price,
    get_latest_snapshot,
    get_previous_snapshot,
    get_price_history,
    get_recent_logs,
    get_sticky_top_flight_keys,
    get_tracker,
    get_tracker_stats,
    get_tracker_summaries,
    insert_log,
    list_trackers,
    update_tracker,
)

CHART_COLORS = [
    "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
    "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
]


def _assign_chart_colors(flight_keys: list[str]) -> dict[str, str]:
    return {key: CHART_COLORS[i % len(CHART_COLORS)] for i, key in enumerate(flight_keys)}


_env = Environment(
    loader=FileSystemLoader("frontend/templates"),
    autoescape=select_autoescape(),
    cache_size=0,
)

router = APIRouter()

_logo_cache: dict[str, bytes | None] = {}


_CDN = "https://images.kiwi.com/airlines/128"


@router.get("/airline-logo/{code}")
async def airline_logo_proxy(code: str):
    code = code.upper()
    if code in _logo_cache:
        data = _logo_cache[code]
        if data is None:
            return RedirectResponse(url=f"{_CDN}/{code}.png", status_code=302)
        return Response(content=data, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_CDN}/{code}.png")
        if resp.status_code == 200:
            _logo_cache[code] = resp.content
            return Response(content=resp.content,
                            media_type=resp.headers.get("content-type", "image/png"),
                            headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        pass
    _logo_cache[code] = None
    return RedirectResponse(url=f"{_CDN}/{code}.png", status_code=302)


def _render(name: str, context: dict) -> HTMLResponse:
    template = _env.get_template(name)
    return HTMLResponse(template.render(context))


def _format_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        now = datetime.now()
        if dt.year == now.year:
            return dt.strftime("%B %-d")
        return dt.strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return date_str


_env.filters["format_date"] = _format_date

LOGO_UNAVAILABLE_CODES: set[str] = set()

_IATA_RE = re.compile(r"^[A-Z0-9]{2}$")


def _airline_code(flight_number: str | None) -> str:
    if not flight_number:
        return ""
    token = str(flight_number).strip().split(" ", 1)[0].upper()
    if not _IATA_RE.match(token):
        return ""
    if token in LOGO_UNAVAILABLE_CODES:
        return ""
    return token


_env.filters["airline_code"] = _airline_code

_CURRENCY_SYMBOLS: dict[str, str] = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}
_env.filters["currency_symbol"] = lambda c: _CURRENCY_SYMBOLS.get(c or "", (c or "") + " ")


def _split_timestamps(flight_dict: dict) -> None:
    raw_dates: dict[str, str] = {}
    for key in ("departure_time", "arrival_time"):
        val = flight_dict.get(key)
        if val and "T" in str(val):
            date_part, time_with_tz = str(val).split("T", 1)
            tz_suffix = ""
            if "+" in time_with_tz:
                tz_suffix = " +" + time_with_tz.split("+", 1)[1].split(":", 1)[0] + ":" + time_with_tz.split("+", 1)[1].split(":", 2)[1][:2]
            time_part = time_with_tz.split("+")[0].split("-")[0].split("Z")[0]
            if len(time_part) >= 5:
                time_part = time_part[:5]
            flight_dict[key + "_date"] = _format_date(date_part)
            flight_dict[key + "_time"] = time_part + tz_suffix
            raw_dates[key] = date_part
    dep = raw_dates.get("departure_time")
    arr = raw_dates.get("arrival_time")
    offset = 0
    if dep and arr:
        try:
            offset = (datetime.fromisoformat(arr).date() - datetime.fromisoformat(dep).date()).days
        except (ValueError, TypeError):
            pass
    flight_dict["arrival_day_offset"] = offset


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
        origin=form["origin"].upper().strip(),
        destination=form["destination"].upper().strip(),
        depart_date=form["depart_date"],
        return_date=form.get("return_date") or None,
        top_n=5,
    )
    await insert_log("INFO", "tracker_created", tracker_id=tracker["id"],
                     message=f"{tracker['origin']} -> {tracker['destination']}")

    await backend.scheduler.search_and_store(tracker["id"])
    backend.scheduler.add_tracker_job(tracker["id"], tracker["interval_minutes"], run_immediately=False)

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
        await insert_log("INFO", "tracker_resumed", tracker_id=tracker_id)
    else:
        backend.scheduler.remove_tracker_job(tracker_id)
        await insert_log("INFO", "tracker_paused", tracker_id=tracker_id)

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
        prev_flights = {p["flight_key"]: p for p in prev}
    else:
        prev_flights = {}

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
        _split_timestamps(item["flight"])

    current_keys = {f["flight"]["flight_key"] for f in flights_with_delta}
    for key, prev_flight in prev_flights.items():
        if key not in current_keys:
            missing = dict(prev_flight)
            flights_with_delta.append({
                "flight": missing,
                "delta": {"type": "missing"},
            })

    for item in flights_with_delta:
        if item.get("delta", {}).get("type") == "missing":
            _split_timestamps(item["flight"])

    history = await get_price_history(tracker_id)

    top_n = tracker["top_n"]
    # ordered by price ascending (flights_with_delta is already price-asc from the DB query)
    ordered_top_keys = [
        f["flight"]["flight_key"]
        for f in flights_with_delta[:top_n]
        if f.get("delta", {}).get("type") != "missing"
    ]
    # pre-create datasets in price-rank order with label from current flight data
    chart_datasets = {}
    for f in flights_with_delta[:top_n]:
        if f.get("delta", {}).get("type") == "missing":
            continue
        key = f["flight"]["flight_key"]
        flight = f["flight"]
        label = (flight.get("flight_number") or "").strip() or flight.get("airline", "") or key
        chart_datasets[key] = {"label": label, "data": []}

    flight_key_colors = _assign_chart_colors(ordered_top_keys)
    for key, entry in chart_datasets.items():
        entry["color"] = flight_key_colors[key]

    # group history by flight_key for chart datasets and all_flights
    history_by_key: dict[str, list] = {}
    for row in history:
        key = row["flight_key"]
        if key not in history_by_key:
            history_by_key[key] = []
        history_by_key[key].append({
            "x": row["searched_at"].replace(" ", "T"),
            "y": row["price"],
        })

    for key, entry in chart_datasets.items():
        entry["data"] = history_by_key.get(key, [])

    all_flights = []
    for f in flights_with_delta:
        if f.get("delta", {}).get("type") == "missing":
            continue
        flight = f["flight"]
        key = flight["flight_key"]
        label = (flight.get("flight_number") or "").strip() or flight.get("airline", "") or key
        all_flights.append({
            "flight_key": key,
            "label": label,
            "price": flight["price"],
            "stops": flight.get("stops"),
            "duration_min": flight.get("duration_min"),
            "airline": flight.get("airline"),
            "data": history_by_key.get(key, []),
        })

    max_stops = max((f["stops"] for f in all_flights if f.get("stops") is not None), default=0)
    max_duration = max((f["duration_min"] for f in all_flights if f.get("duration_min") is not None), default=0)

    airline_groups: dict[str, dict] = {}
    for f in all_flights:
        name = f["airline"] or ""
        if name not in airline_groups:
            airline_groups[name] = {"name": name, "count": 0, "best_price": f["price"]}
        airline_groups[name]["count"] += 1
        if f["price"] < airline_groups[name]["best_price"]:
            airline_groups[name]["best_price"] = f["price"]
    airlines = sorted(airline_groups.values(), key=lambda a: (a["best_price"], a["name"]))

    best_price = min((f["flight"]["price"] for f in flights_with_delta if f.get("delta", {}).get("type") != "missing"), default=None)
    historical_best_price = await get_historical_best_price(tracker_id)

    return {
        "tracker": tracker,
        "latest_snapshot": latest,
        "flights_with_delta": flights_with_delta,
        "chart_datasets": json.dumps(list(chart_datasets.values())),
        "all_flights": json.dumps(all_flights),
        "flight_key_colors": flight_key_colors,
        "max_stops": max_stops,
        "max_duration": max_duration,
        "best_price": best_price,
        "historical_best_price": historical_best_price,
        "airlines": airlines,
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
    return _render("partials/detail_page.html", ctx)


@router.delete("/trackers/{tracker_id}", response_class=HTMLResponse)
async def delete_tracker_card(request: Request, tracker_id: int):
    tracker = await get_tracker(tracker_id)
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)

    if tracker:
        await insert_log("INFO", "tracker_deleted", tracker_id=tracker_id,
                         message=f"{tracker['origin']} -> {tracker['destination']}")

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
        await insert_log("INFO", "tracker_resumed", tracker_id=tracker_id)
    else:
        backend.scheduler.remove_tracker_job(tracker_id)
        await insert_log("INFO", "tracker_paused", tracker_id=tracker_id)

    ctx = await _build_detail_context(tracker_id)
    ctx["request"] = request
    return _render("partials/detail_page.html", ctx)


@router.delete("/trackers/{tracker_id}/detail", response_class=HTMLResponse)
async def delete_tracker_detail(request: Request, tracker_id: int):
    backend.scheduler.remove_tracker_job(tracker_id)
    await delete_tracker(tracker_id)

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/"
    return response


@router.post("/refresh-all", response_class=HTMLResponse)
async def refresh_all(request: Request):
    trackers = await list_trackers()
    for tracker in trackers:
        if tracker["active"]:
            await backend.scheduler.search_and_store(tracker["id"])

    summaries = _enrich_summaries(await get_tracker_summaries())
    return _render("dashboard.html", {"request": request, "trackers": summaries})


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    logs = await get_recent_logs(limit=500)
    tracker_stats = await get_tracker_stats()
    db_stats = await get_db_stats()
    return _render("monitor.html", {
        "request": request,
        "logs": logs,
        "tracker_stats": tracker_stats,
        "db_stats": db_stats,
    })


@router.get("/monitor/logs", response_class=HTMLResponse)
async def monitor_logs():
    logs = await get_recent_logs(limit=500)
    return _render("partials/monitor_logs.html", {"logs": logs})
