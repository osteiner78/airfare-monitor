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
    get_best_price_series,
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

_CURRENCY_SYMBOLS: dict[str, str] = {"EUR": "€ ", "USD": "$ ", "GBP": "£ ", "CHF": "CHF "}
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


def _compute_delta(current: float | None, reference: float | None) -> dict | None:
    if current is None or reference is None:
        return None
    if current < reference:
        return {"type": "down", "amount": round(reference - current, 2)}
    if current > reference:
        return {"type": "up", "amount": round(current - reference, 2)}
    return {"type": "same"}


_MIN_SPAN_FRAC = 0.06


def _sparkline(prices: list[float], w: int = 132, h: int = 34, pad: int = 4) -> dict | None:
    pts = [p for p in prices if p is not None]
    if len(pts) < 2:
        return None
    lo, hi = min(pts), max(pts)
    mid = (lo + hi) / 2
    floor = mid * _MIN_SPAN_FRAC
    span = max(hi - lo, floor, 1e-9)
    elo = mid - span / 2
    n = len(pts)

    def x(i: int) -> float:
        return round(pad + (w - 2 * pad) * i / (n - 1), 1)

    def y(p: float) -> float:
        return round(pad + (h - 2 * pad) * (1 - (p - elo) / span), 1)

    coords = [(x(i), y(p)) for i, p in enumerate(pts)]
    line = " ".join(f"{cx},{cy}" for cx, cy in coords)
    area = f"{coords[0][0]},{h} {line} {coords[-1][0]},{h}"
    first, last = pts[0], pts[-1]
    trend = "down" if last < first else "up" if last > first else "flat"
    label_h = 11

    low_idx = max(i for i, p in enumerate(pts) if p == lo)
    low_cx, low_cy = coords[low_idx]

    return {
        "points": line,
        "area": area,
        "low_x": low_cx,
        "low_y": low_cy,
        "low_price": lo,
        "last_x": coords[-1][0],
        "last_y": coords[-1][1],
        "last_price": last,
        "label_y": h + label_h - 2,
        "trend": trend,
        "w": w,
        "h": h + label_h,
    }


def _enrich_summaries(summaries: list, series: dict[int, list[float]] | None = None) -> list:
    series = series or {}
    for s in summaries:
        best = s.get("best_price")
        s["price_delta"] = _compute_delta(best, s.get("previous_best_price"))
        s["delta_creation"] = _compute_delta(best, s.get("best_price_at_creation"))
        s["delta_24h"] = _compute_delta(best, s.get("best_price_24h_ago"))
        s["delta_3h"] = _compute_delta(best, s.get("best_price_3h_ago"))
        s["spark"] = _sparkline(series.get(s["id"], []))
    return summaries


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summaries = await get_tracker_summaries()
    summaries = _enrich_summaries(summaries, await get_best_price_series())
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

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
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

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
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
    sticky_keys = await get_sticky_top_flight_keys(tracker_id, top_n)

    def _flight_label(flight: dict) -> str:
        num = (flight.get("flight_number") or "").strip()
        airline = (flight.get("airline") or "").strip()
        if num and airline:
            return f"{airline} {num}"
        return num or airline or flight.get("flight_key", "")

    # Index current non-missing flights by key for label lookup.
    current_flight_map = {
        f["flight"]["flight_key"]: f["flight"]
        for f in flights_with_delta
        if f.get("delta", {}).get("type") != "missing"
    }

    # Build history series and keep the most-recent row per key for label fallback.
    history_by_key: dict[str, list] = {}
    history_latest: dict[str, dict] = {}
    for row in history:
        key = row["flight_key"]
        if key not in history_by_key:
            history_by_key[key] = []
        history_by_key[key].append({"x": row["searched_at"].replace(" ", "T"), "y": row["price"]})
        history_latest[key] = row  # history is ASC so last write = most recent

    def _label_for_key(key: str) -> str:
        if key in current_flight_map:
            return _flight_label(current_flight_map[key])
        if key in history_latest:
            return _flight_label(history_latest[key])
        return key

    # Current top-N keys in price order → determine color rank.
    ordered_top_keys = [
        f["flight"]["flight_key"]
        for f in flights_with_delta[:top_n]
        if f.get("delta", {}).get("type") != "missing"
    ]
    # Sticky keys that are not in the current top-N (ever-cheap, now displaced).
    top_key_set = set(ordered_top_keys)
    sticky_extras = [k for k in sticky_keys if k not in top_key_set]
    all_chart_keys = ordered_top_keys + sticky_extras

    all_chart_colors = _assign_chart_colors(all_chart_keys)

    # flight_key_colors drives row highlighting — only non-missing current flights
    # so that missing rows keep their neutral style even when tracked in the chart.
    non_missing_chart_keys = [k for k in all_chart_keys if k in current_flight_map]
    flight_key_colors = _assign_chart_colors(non_missing_chart_keys)

    chart_datasets = {
        key: {
            "label": _label_for_key(key),
            "color": all_chart_colors[key],
            "data": history_by_key.get(key, []),
        }
        for key in all_chart_keys
    }

    all_flights = []
    for f in flights_with_delta:
        if f.get("delta", {}).get("type") == "missing":
            continue
        flight = f["flight"]
        key = flight["flight_key"]
        all_flights.append({
            "flight_key": key,
            "label": _flight_label(flight),
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
        "sticky_flight_keys": json.dumps(list(sticky_keys)),
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

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
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

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
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
