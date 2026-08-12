import json
import re
from datetime import datetime

import backend.scheduler
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.db import (
    DEFAULT_INTERVAL_MINUTES,
    create_tracker,
    delete_tracker,
    get_best_price_series,
    get_db_stats,
    get_flight_prices_for_snapshots,
    get_historical_best_price,
    get_latest_snapshot,
    get_source_observations,
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


_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_ts(value):
    if not value:
        return None
    text = str(value).split(".")[0]
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# FallbackSource runs fast_flights ONLY when fli returns nothing, so the two
# are alternate scrapers of one upstream rather than independent sources.
# Blending them separately resurrects a stale fallback set beside fresh primary
# rows -- the same flights listed twice at different ages.
_BLEND_GROUPS = {"google_flights": "google", "fast_flights": "google"}


def _blend_group(source: str) -> str:
    return _BLEND_GROUPS.get(source, source)


def _age_minutes(observed_at, newest_at) -> float:
    """How far behind the newest observation this one is, in minutes.

    Measured against the newest snapshot rather than wall-clock now, so the
    badge answers "older than the rest of this page" -- which is the thing
    that makes a blended row worth flagging. Unparseable timestamps count as
    fresh: refusing to display a row because its timestamp could not be parsed
    would lose real prices over a formatting detail.
    """
    a, b = _parse_ts(observed_at), _parse_ts(newest_at)
    if a is None or b is None:
        return 0.0
    return max(0.0, (b - a).total_seconds() / 60.0)


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


def _format_card_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%a %-d %b")
    except (ValueError, TypeError):
        return date_str


_env.filters["format_card_date"] = _format_card_date


def _format_date_short(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%b %-d")
    except (ValueError, TypeError):
        return date_str


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

# Kayak's collapsed list view prints no flight number, so the flight_number ->
# IATA code path (_airline_code above) never resolves for its rows. This maps
# the full airline names Kayak/Google actually print to their IATA code, so
# those rows can still get a logo. Deliberately excludes generated labels
# like "Multiple airlines" (Kayak's own placeholder for a multi-carrier
# self-transfer itinerary, not a bookable airline) -- an unmapped name falls
# back to plain text, which is the correct outcome for those.
_AIRLINE_NAME_TO_CODE: dict[str, str] = {
    "TAP AIR PORTUGAL": "TP",
    "TAP PORTUGAL": "TP",
    "AZUL": "AD",
    "AIR EUROPA": "UX",
    "ITA AIRWAYS": "AZ",
    "IBERIA": "IB",
    "ARAJET": "DM",
    "GOL": "G3",
    "LUFTHANSA": "LH",
    "AIR FRANCE": "AF",
    "KLM": "KL",
    "EMIRATES": "EK",
    "TURKISH AIRLINES": "TK",
    "UNITED": "UA",
    "UNITED AIRLINES": "UA",
    "AVIANCA": "AV",
    "SWISS": "LX",
    "BRITISH AIRWAYS": "BA",
    "DELTA": "DL",
    "DELTA AIR LINES": "DL",
    "AIR CANADA": "AC",
    "AEROMEXICO": "AM",
    "LATAM": "LA",
    "LATAM AIRLINES": "LA",
    "AMERICAN AIRLINES": "AA",
    "AMERICAN": "AA",
    "EASYJET": "U2",
    "VUELING": "VY",
    "RYANAIR": "FR",
    "NORWEGIAN": "DY",
    "NORWEGIAN AIR SHUTTLE": "DY",
    "FINNAIR": "AY",
    "AUSTRIAN": "OS",
    "AUSTRIAN AIRLINES": "OS",
    "BRUSSELS AIRLINES": "SN",
    "LOT POLISH AIRLINES": "LO",
    "COPA AIRLINES": "CM",
    "QATAR AIRWAYS": "QR",
    "ETIHAD AIRWAYS": "EY",
    "SINGAPORE AIRLINES": "SQ",
    "CATHAY PACIFIC": "CX",
    "ANA": "NH",
    "ALL NIPPON AIRWAYS": "NH",
    "JAPAN AIRLINES": "JL",
    "ALASKA AIRLINES": "AS",
    "JETBLUE": "B6",
    "SOUTHWEST": "WN",
    "WESTJET": "WS",
    "AIR INDIA": "AI",
    "ETHIOPIAN AIRLINES": "ET",
    "KENYA AIRWAYS": "KQ",
    "SOUTH AFRICAN AIRWAYS": "SA",
    "ROYAL AIR MAROC": "AT",
    "EGYPTAIR": "MS",
    "SAUDIA": "SV",
    "AEROFLOT": "SU",
    "WIZZ AIR": "W6",
    "VOLARIS": "Y4",
}


def _airline_code_from_name(name: str | None) -> str:
    if not name:
        return ""
    key = " ".join(str(name).split()).upper()
    code = _AIRLINE_NAME_TO_CODE.get(key, "")
    if code in LOGO_UNAVAILABLE_CODES:
        return ""
    return code


_env.filters["airline_code_from_name"] = _airline_code_from_name

_CURRENCY_SYMBOLS: dict[str, str] = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}
_env.filters["currency_symbol"] = lambda c: _CURRENCY_SYMBOLS.get(c or "", (c or "") + " ")

_SOURCE_LABELS: dict[str, str] = {
    "google_flights": "Google Flights",
    "fast_flights": "Google Flights (alt)",
    "kayak": "Kayak",
}
_env.filters["source_label"] = lambda s: _SOURCE_LABELS.get(s, s)


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
            flight_dict[key + "_date"] = _format_date_short(date_part)
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


def _group_duplicate_price_rows(flights_with_delta: list[dict]) -> list[dict]:
    """Collapse rows that are true duplicates -- same flight_key AND the same
    price, just quoted by more than one source -- into a single row listing
    every source. Rows sharing a flight_key at DIFFERENT prices stay split:
    that disagreement is the whole point of tracking more than one source,
    so only an exact match is clutter rather than information.

    The kept row's display fields (times, duration, flight number) come from
    whichever source's row is seen first, except flight_number is adopted
    from a later source if the first one didn't have one -- Kayak's
    collapsed view never prints one, so a duplicate Google row shouldn't
    lose it. Freshness (observed_at/age_minutes/is_stale) and the delta
    badge come from whichever source observation is freshest.
    """
    grouped: list[dict] = []
    merged_by_key: dict[tuple, dict] = {}
    for item in flights_with_delta:
        flight = item["flight"]
        is_missing = item.get("delta", {}).get("type") == "missing"
        group_key = (flight["flight_key"], flight["price"], is_missing)
        existing = merged_by_key.get(group_key)
        if existing is None:
            merged_item = dict(item)
            merged_item["flight"] = dict(flight)
            merged_item["sources"] = [flight.get("source")]
            merged_by_key[group_key] = merged_item
            grouped.append(merged_item)
            continue
        existing["sources"].append(flight.get("source"))
        if not existing["flight"].get("flight_number") and flight.get("flight_number"):
            existing["flight"]["flight_number"] = flight.get("flight_number")
        existing_age = existing["flight"].get("age_minutes")
        new_age = flight.get("age_minutes")
        if new_age is not None and (existing_age is None or new_age < existing_age):
            existing["flight"]["observed_at"] = flight.get("observed_at")
            existing["flight"]["age_minutes"] = new_age
            existing["flight"]["is_stale"] = flight.get("is_stale")
            existing["delta"] = item["delta"]
    return grouped


_MIN_SPAN_FRAC = 0.06
_MIN_GAP_FRAC = 0.40
_RAIL_MARGIN = 0.14


def _rail_positions(current_frac: float, low_frac: float) -> tuple[float, float]:
    c, a = current_frac, low_frac
    if a - c < _MIN_GAP_FRAC:
        m = (c + a) / 2
        c, a = m - _MIN_GAP_FRAC / 2, m + _MIN_GAP_FRAC / 2
    if c < _RAIL_MARGIN:
        c, a = _RAIL_MARGIN, max(a, _RAIL_MARGIN + _MIN_GAP_FRAC)
    if a > 1 - _RAIL_MARGIN:
        a, c = 1 - _RAIL_MARGIN, min(c, 1 - _RAIL_MARGIN - _MIN_GAP_FRAC)
    return round(c, 4), round(a, 4)


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

    low_idx = max(i for i, p in enumerate(pts) if p == lo)
    low_cx, low_cy = coords[low_idx]

    last_x_frac = round(coords[-1][0] / w, 4)
    last_y_frac = round(coords[-1][1] / h, 4)
    low_x_frac = round(low_cx / w, 4)
    low_y_frac = round(low_cy / h, 4)
    at_all_time_low = last == lo
    current_rail, alltime_rail = _rail_positions(last_y_frac, low_y_frac)

    return {
        "points": line,
        "area": area,
        "low_x": low_cx,
        "low_y": low_cy,
        "low_price": lo,
        "last_x": coords[-1][0],
        "last_y": coords[-1][1],
        "last_price": last,
        "last_x_frac": last_x_frac,
        "last_y_frac": last_y_frac,
        "low_x_frac": low_x_frac,
        "low_y_frac": low_y_frac,
        "at_all_time_low": at_all_time_low,
        "current_rail": current_rail,
        "alltime_rail": alltime_rail,
        "trend": trend,
        "w": w,
        "h": h,
    }


def _primary_delta(summary: dict) -> dict | None:
    candidates = [
        ("3h", summary.get("delta_3h")),
        ("24h", summary.get("delta_24h")),
        ("start", summary.get("delta_creation")),
    ]
    for period, d in candidates:
        if d is not None and d.get("type") in ("up", "down"):
            return {"period": period, "type": d["type"], "amount": d.get("amount")}
    return None


def _enrich_summaries(summaries: list, series: dict[int, list[float]] | None = None) -> list:
    series = series or {}
    for s in summaries:
        best = s.get("best_price")
        s["price_delta"] = _compute_delta(best, s.get("previous_best_price"))
        s["delta_creation"] = _compute_delta(best, s.get("best_price_at_creation"))
        s["delta_24h"] = _compute_delta(best, s.get("best_price_24h_ago"))
        s["delta_3h"] = _compute_delta(best, s.get("best_price_3h_ago"))
        s["primary_delta"] = _primary_delta(s)
        s["spark"] = _sparkline(series.get(s["id"], []))
    return summaries


def _split_by_departure(summaries: list) -> tuple[list, list]:
    today = datetime.now().date().isoformat()
    upcoming = [s for s in summaries if s["depart_date"] >= today]
    past = [s for s in summaries if s["depart_date"] < today]
    return upcoming, past


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summaries = await get_tracker_summaries()
    summaries = _enrich_summaries(summaries, await get_best_price_series())
    upcoming, past = _split_by_departure(summaries)
    return _render("dashboard.html", {"request": request, "trackers": upcoming, "past_trackers": past})


@router.post("/", response_class=HTMLResponse)
async def add_tracker(request: Request):
    form = await request.form()
    tracker = await create_tracker(
        origin=form["origin"].upper().strip(),
        destination=form["destination"].upper().strip(),
        depart_date=form["depart_date"],
        return_date=form.get("return_date") or None,
        top_n=5,
        # Passed explicitly: the schema's own DEFAULT only applies to
        # newly created databases, and production's trackers table was
        # built when the default was still 180.
        interval_minutes=DEFAULT_INTERVAL_MINUTES,
    )
    await insert_log("INFO", "tracker_created", tracker_id=tracker["id"],
                     message=f"{tracker['origin']} -> {tracker['destination']}")

    await backend.scheduler.search_and_store(tracker["id"], delay=False)
    backend.scheduler.add_tracker_job(tracker["id"], tracker["interval_minutes"], run_immediately=False)

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
    upcoming, past = _split_by_departure(summaries)
    return _render("partials/tracker_list.html", {"request": request, "trackers": upcoming, "past_trackers": past})


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

    # Blend the latest observation of EACH source rather than reading a single
    # snapshot. A Google-only cycle used to make Kayak's rows look "missing"
    # (i.e. those fares vanished) when the truth was only that Kayak had not
    # run; two such cycles in a row dropped them from the page entirely,
    # because the missing-row reconstruction looked back exactly one snapshot.
    # This is a read-time join and nothing is written: carrying rows forward
    # into new snapshots would fabricate chart points, and historical_best_price
    # is MIN over all rows and never recomputed, so a re-inserted stale price
    # would distort the all-time low permanently.
    observations = await get_source_observations(tracker_id, per_source=2)

    # Beyond this, a source's rows are dropped rather than shown: a fare from
    # several cycles ago is not "current" in any useful sense, and quietly
    # presenting it as such is worse than showing nothing.
    max_age_minutes = max(2 * (tracker["interval_minutes"] or 60), 60)
    newest_searched_at = latest["searched_at"] if latest else None

    # Blend by GROUP, not by raw source. `google_flights` and `fast_flights`
    # are the same upstream (Google) behind FallbackSource, which only runs the
    # secondary when the primary comes back empty -- they are mutually
    # exclusive by construction, not independent opinions. Treating them
    # separately kept a stale fast_flights set alive next to fresh
    # google_flights rows, showing the same flights twice with different ages.
    by_group: dict[str, list[dict]] = {}
    for obs in observations:
        by_group.setdefault(_blend_group(obs["source"]), []).append(obs)

    latest_by_group: dict[str, dict] = {}
    previous_by_group: dict[str, dict] = {}
    for group, group_observations in by_group.items():
        seen: dict[int, dict] = {}
        for obs in group_observations:
            seen.setdefault(obs["snapshot_id"], obs)
        ordered = sorted(seen.values(), key=lambda o: o["snapshot_id"], reverse=True)
        if _age_minutes(ordered[0]["searched_at"], newest_searched_at) > max_age_minutes:
            continue
        latest_by_group[group] = ordered[0]
        if len(ordered) > 1:
            previous_by_group[group] = ordered[1]

    wanted_snapshots = {o["snapshot_id"] for o in latest_by_group.values()}
    wanted_snapshots |= {o["snapshot_id"] for o in previous_by_group.values()}
    rows = await get_flight_prices_for_snapshots(sorted(wanted_snapshots))

    current_flights = []
    prev_rows_by_group: dict[str, dict] = {}
    for row in rows:
        group = _blend_group(row.get("source") or "")
        latest_obs = latest_by_group.get(group)
        if latest_obs and row["snapshot_id"] == latest_obs["snapshot_id"]:
            row["observed_at"] = latest_obs["searched_at"]
            row["age_minutes"] = _age_minutes(latest_obs["searched_at"], newest_searched_at)
            row["is_stale"] = row["age_minutes"] > 0
            current_flights.append(row)
            continue
        prev_obs = previous_by_group.get(group)
        if prev_obs and row["snapshot_id"] == prev_obs["snapshot_id"]:
            row["observed_at"] = prev_obs["searched_at"]
            row["age_minutes"] = _age_minutes(prev_obs["searched_at"], newest_searched_at)
            prev_rows_by_group.setdefault(group, {}).setdefault(row["flight_key"], row)

    # rows is ORDER BY price ASC, and the per-snapshot ordering is preserved
    # within it, but concatenating sources breaks the global order.
    current_flights.sort(key=lambda r: r["price"])

    flights_with_delta = []
    for flight in current_flights:
        # Deltas are per SOURCE: comparing Kayak's price now against whatever
        # Google quoted in some intervening snapshot is not a price movement.
        prev_for_source = prev_rows_by_group.get(_blend_group(flight.get("source") or ""), {})
        prev_row = prev_for_source.get(flight["flight_key"])
        prev_price = prev_row["price"] if prev_row else None
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

    prev_flights = {}
    for group, by_key in prev_rows_by_group.items():
        for key, row in by_key.items():
            prev_flights.setdefault(key, row)

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

    top_n = tracker["top_n"]
    sticky_keys = await get_sticky_top_flight_keys(tracker_id, top_n)

    def _flight_label(flight: dict) -> str:
        num = (flight.get("flight_number") or "").strip()
        airline = (flight.get("airline") or "").strip()
        if num and airline:
            return f"{airline} {num}"
        return num or airline or flight.get("flight_key", "")

    # Index current non-missing flights by key for label lookup. current_flights
    # is ORDER BY price ASC; setdefault keeps the cheapest row per flight_key.
    current_flight_map = {}
    for f in flights_with_delta:
        if f.get("delta", {}).get("type") != "missing":
            current_flight_map.setdefault(f["flight"]["flight_key"], f["flight"])

    # Only fetch history for flight_keys the chart / window.allFlights actually
    # need: every current flight (filters.js can promote any of them into the
    # visible chart on a filter change) plus sticky keys (ever-cheap, possibly
    # no longer current). A tracker accumulates snapshots forever, so pulling
    # every distinct flight_key it's ever seen (tens of thousands of rows for
    # a months-old tracker) here was the dominant cost of loading this page.
    history_keys = set(current_flight_map) | sticky_keys
    history = await get_price_history(tracker_id, flight_keys=list(history_keys)) if history_keys else []

    # Build history series and keep the most-recent row per key for label fallback.
    # history is ORDER BY searched_at ASC. Two sources quoting the same flight_key
    # in one snapshot produce two rows sharing that snapshot's flight_key -- merge
    # those into one point (cheapest price wins), keyed by snapshot_id rather than
    # the formatted timestamp string: two DIFFERENT snapshots can legitimately
    # share the same second-resolution searched_at (e.g. two inserts in quick
    # succession), and those must stay as separate chart points.
    history_by_key: dict[str, list] = {}
    history_latest: dict[str, dict] = {}
    _last_snapshot_for_key: dict[str, int] = {}
    for row in history:
        key = row["flight_key"]
        ts = row["searched_at"].replace(" ", "T")
        points = history_by_key.setdefault(key, [])
        if points and _last_snapshot_for_key.get(key) == row["snapshot_id"]:
            if row["price"] < points[-1]["y"]:
                points[-1]["y"] = row["price"]
        else:
            points.append({"x": ts, "y": row["price"]})
            _last_snapshot_for_key[key] = row["snapshot_id"]
        history_latest[key] = row  # history is ASC so last write = most recent

    def _label_for_key(key: str) -> str:
        if key in current_flight_map:
            return _flight_label(current_flight_map[key])
        if key in history_latest:
            return _flight_label(history_latest[key])
        return key

    # Current top-N keys in price order → determine color rank. Walk in order
    # and keep the first (cheapest) occurrence of each distinct flight_key,
    # stopping at top_n distinct keys -- a duplicated key must not consume two
    # colour slots.
    ordered_top_keys = []
    _seen_top_keys = set()
    for f in flights_with_delta:
        if f.get("delta", {}).get("type") == "missing":
            continue
        key = f["flight"]["flight_key"]
        if key in _seen_top_keys:
            continue
        _seen_top_keys.add(key)
        ordered_top_keys.append(key)
        if len(ordered_top_keys) >= top_n:
            break
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
            "flight_key": key,
            "label": _label_for_key(key),
            "color": all_chart_colors[key],
            "data": history_by_key.get(key, []),
        }
        for key in all_chart_keys
    }

    all_flights = []
    _seen_all_flight_keys = set()
    for f in flights_with_delta:
        if f.get("delta", {}).get("type") == "missing":
            continue
        flight = f["flight"]
        key = flight["flight_key"]
        if key in _seen_all_flight_keys:
            continue
        _seen_all_flight_keys.add(key)
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

    # "Best now" is the cheapest across the BLENDED set, so a Kayak fare that
    # is genuinely the cheapest still wins even when Kayak did not run in the
    # newest cycle. When the winner is not from the freshest observation the
    # template shows its age, because the honest claim is "cheapest we know
    # of, seen N minutes ago", not "cheapest right now".
    live_rows = [f["flight"] for f in flights_with_delta
                 if f.get("delta", {}).get("type") != "missing"]
    best_row = min(live_rows, key=lambda r: r["price"], default=None)
    best_price = best_row["price"] if best_row else None
    best_price_source = best_row.get("source") if best_row else None
    best_price_age_minutes = int(best_row.get("age_minutes") or 0) if best_row else 0
    best_price_is_stale = bool(best_row and best_row.get("is_stale"))
    historical_best_price = await get_historical_best_price(tracker_id)

    # Per-row sparkline for the results table -- one flight's own price history,
    # reusing the same history_by_key data already fetched for the chart.
    row_sparklines: dict[str, dict | None] = {}
    for item in flights_with_delta:
        key = item["flight"]["flight_key"]
        if key in row_sparklines:
            continue
        prices = [p["y"] for p in history_by_key.get(key, [])]
        row_sparklines[key] = _sparkline(prices, w=64, h=20, pad=2)

    source_freshness = [
        {
            "source": source,
            "searched_at": obs["searched_at"],
            "age_minutes": int(_age_minutes(obs["searched_at"], newest_searched_at)),
        }
        for source, obs in sorted(latest_by_group.items())
    ]

    table_rows = _group_duplicate_price_rows(flights_with_delta)

    return {
        "tracker": tracker,
        "latest_snapshot": latest,
        "flights_with_delta": table_rows,
        "chart_datasets": json.dumps(list(chart_datasets.values())),
        "all_flights": json.dumps(all_flights),
        "sticky_flight_keys": json.dumps(list(sticky_keys)),
        "flight_key_colors": flight_key_colors,
        "row_sparklines": row_sparklines,
        "max_stops": max_stops,
        "max_duration": max_duration,
        "best_price": best_price,
        "best_price_source": best_price_source,
        "best_price_age_minutes": best_price_age_minutes,
        "best_price_is_stale": best_price_is_stale,
        "source_freshness": source_freshness,
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
    await backend.scheduler.search_and_store(tracker_id, delay=False)
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
    upcoming, past = _split_by_departure(summaries)
    return _render("partials/tracker_list.html", {"request": request, "trackers": upcoming, "past_trackers": past})


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


@router.patch("/trackers/{tracker_id}/toggle-kayak", response_class=HTMLResponse)
async def toggle_tracker_kayak(request: Request, tracker_id: int):
    tracker = await get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found")

    new_kayak_enabled = not tracker["kayak_enabled"]
    await update_tracker(tracker_id, kayak_enabled=new_kayak_enabled)

    if new_kayak_enabled:
        await insert_log("INFO", "kayak_enabled", tracker_id=tracker_id)
    else:
        await insert_log("INFO", "kayak_disabled", tracker_id=tracker_id)

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
            await backend.scheduler.search_and_store(tracker["id"], delay=False)

    summaries = _enrich_summaries(await get_tracker_summaries(), await get_best_price_series())
    upcoming, past = _split_by_departure(summaries)
    return _render("dashboard.html", {"request": request, "trackers": upcoming, "past_trackers": past})


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
