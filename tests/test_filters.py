"""Tests for plan 010 — tracker-page filter sidebar (stops + duration).

Automated coverage targets the SERVER side only: the data contract shipped to the
browser (`window.allFlights`), the per-row filter attributes, and the server-rendered
sidebar controls. The client-side filtering BEHAVIOUR (greying rows, recomputing the
chart) has no automated coverage — this repo is pytest-only with no JS test runner —
and is verified via the manual smoke matrix in .agent/reports/010-phase-4.md.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.
  NON-REGRESSION               -> must already pass against current code.
"""

import json
import re

import pytest


def _extract_js_global(text: str, name: str):
    """Pull `window.<name> = <json>;</script>` out of a rendered page and parse it.
    Returns None when the global is absent, so fail-first tests fail on a real
    assertion rather than a regex/JSON crash."""
    match = re.search(r"window\." + re.escape(name) + r" = (.*?);</script>", text, re.DOTALL)
    if match is None:
        return None
    return json.loads(match.group(1))


async def _make_tracker(client):
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })


def _price(flight_key, price, **over):
    base = {
        "flight_key": flight_key, "source": "test", "price": float(price), "currency": "EUR",
        "airline": "Test", "flight_number": flight_key.split("|")[2],
        "departure_time": "2026-01-01T08:00:00", "arrival_time": "2026-01-01T10:00:00",
        "duration_min": 120, "stops": 0,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Phase 2 — data contract: window.allFlights + per-row attributes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_flights_includes_flight_beyond_top_n(client):
    # top_n default is 5: insert 6 flights at distinct prices. The chart is capped at
    # 5, but allFlights must carry all 6 so a filter can promote the 6th. (off-by-one)
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=6)
    prices = [_price(f"test|XX|{i}|2026-01-01T00:00:00", (i + 1) * 10) for i in range(6)]
    await insert_flight_prices(snap["id"], 1, prices)

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    keys = {f["flight_key"] for f in all_flights}
    assert "test|XX|5|2026-01-01T00:00:00" in keys


@pytest.mark.asyncio
async def test_chart_data_capped_at_top_n_while_all_flights_is_not(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=6)
    prices = [_price(f"test|XX|{i}|2026-01-01T00:00:00", (i + 1) * 10) for i in range(6)]
    await insert_flight_prices(snap["id"], 1, prices)

    response = await client.get("/trackers/1")
    chart = _extract_js_global(response.text, "chartData")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    assert len(chart) == 5
    assert len(all_flights) == 6


@pytest.mark.asyncio
async def test_all_flights_entry_includes_stops_and_duration(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, stops=1, duration_min=345),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    entry = all_flights[0]
    assert entry["stops"] == 1
    assert entry["duration_min"] == 345


@pytest.mark.asyncio
async def test_all_flights_includes_full_history_series_per_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap1 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap1["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])
    snap2 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap2["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 80),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    entry = next(f for f in all_flights if f["flight_key"] == "test|VY|6201|2026-01-01T00:00:00")
    assert len(entry["data"]) == 2


@pytest.mark.asyncio
async def test_row_carries_data_stops_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, stops=0),
    ])

    response = await client.get("/trackers/1")
    assert 'data-stops="0"' in response.text


@pytest.mark.asyncio
async def test_row_carries_data_duration_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=120),
    ])

    response = await client.get("/trackers/1")
    assert 'data-duration="120"' in response.text


@pytest.mark.asyncio
async def test_all_flights_is_empty_array_when_no_snapshot(client):
    # FAILURE-MODE: tracker exists but never searched -> allFlights must be [].
    await _make_tracker(client)
    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights == []


@pytest.mark.asyncio
async def test_row_with_null_duration_renders_empty_data_duration(client):
    # FAILURE-MODE: a flight with unknown duration must render data-duration="" and
    # not crash template rendering.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=None),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'data-duration=""' in response.text


# ---------------------------------------------------------------------------
# Phase 4 — server-rendered sidebar controls (bounds derived from data)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_page_renders_filter_sidebar(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])

    response = await client.get("/trackers/1")
    assert "filter-sidebar" in response.text


@pytest.mark.asyncio
async def test_duration_slider_max_equals_longest_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, duration_min=120),
        _price("test|VY|2|2026-01-01T00:00:00", 110, duration_min=540),
    ])

    response = await client.get("/trackers/1")
    assert 'id="filter-duration"' in response.text
    assert 'max="540"' in response.text


@pytest.mark.asyncio
async def test_stops_select_max_option_equals_most_stops(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=3)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, stops=0),
        _price("test|VY|2|2026-01-01T00:00:00", 110, stops=1),
        _price("test|VY|3|2026-01-01T00:00:00", 120, stops=2),
    ])

    response = await client.get("/trackers/1")
    assert 'id="filter-stops"' in response.text
    assert '<option value="2"' in response.text


@pytest.mark.asyncio
async def test_sidebar_renders_with_single_flight(client):
    # EDGE: single flight -> sidebar still renders.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100),
    ])

    response = await client.get("/trackers/1")
    assert "filter-sidebar" in response.text


@pytest.mark.asyncio
async def test_duration_slider_max_is_zero_when_all_durations_null(client):
    # EDGE: every flight has unknown duration -> slider max collapses to 0, no crash.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, duration_min=None),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'id="filter-duration"' in response.text
    assert 'max="0"' in response.text


# ===========================================================================
# Plan 011 — airline filter
#
# Phase 1 (data contract): airline on window.allFlights + data-airline per row.
#   -> these assert on the JS global / row markup; FAIL before phase 1.
# Phase 2 (sidebar UI): the airline checklist rendered inside <aside
#   class="filter-sidebar">. The facet assertions (count / best price / sort /
#   distinct) need that markup, so they FAIL until phase 2 lands.
#
# Markup contract for the airline checklist (one per airline, cheapest first):
#   <input type="checkbox" class="filter-airline" value="{identity_key}" checked>
#   ... visible "{name or 'Unknown'}" ... "({count})" ... "{best:.2f} {currency}"
#
# Plan 024 phase 5 (F3/A6): value/window.allFlights.airline changed from the
# display name to the stable _airline_identity key -- the display name can
# flip between cycles depending on which source's row is first in the blend,
# which used to invert a persisted (localStorage) filter selection on reload.
# The two tests below were rewritten (assertions, not just fixtures) to match.
# ===========================================================================


def _sidebar(text: str) -> str:
    """Return only the filter-sidebar <aside> body, so facet assertions can't be
    satisfied by coincidental matches in the results table (which repeats prices
    and stop counts)."""
    match = re.search(r'<aside class="filter-sidebar">(.*?)</aside>', text, re.DOTALL)
    return match.group(1) if match else ""


# --- Phase 1: data contract -------------------------------------------------

@pytest.mark.asyncio
async def test_all_flights_entry_airline_is_the_stable_identity_key(client):
    # Plan 024 phase 5 (F3/A6): window.allFlights.airline is the stable
    # _airline_identity key, not the display name, so filters.js keeps
    # matching a saved selection even when the display name flips between
    # cycles. "Vueling" is mapped in AIRLINE_NAME_TO_CODE to "VY", so its
    # identity key is that code, not the casefolded name.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    all_flights = _extract_js_global(response.text, "allFlights")
    assert all_flights is not None, "window.allFlights not emitted"
    assert all_flights[0].get("airline") == "VY"


@pytest.mark.asyncio
async def test_row_carries_data_airline_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    assert 'data-airline="Vueling"' in response.text


@pytest.mark.asyncio
async def test_null_airline_row_renders_empty_data_airline(client):
    # FAILURE-MODE: flight with no airline must render data-airline="" and not crash.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline=None),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'data-airline=""' in response.text


@pytest.mark.asyncio
async def test_airline_with_ampersand_is_escaped_in_data_attribute(client):
    # FAILURE-MODE: special chars in an airline name must be HTML-escaped, not break the attr.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline="AB & CO"),
    ])

    response = await client.get("/trackers/1")
    assert 'data-airline="AB &amp; CO"' in response.text


# --- Phase 2: sidebar airline checklist ------------------------------------

@pytest.mark.asyncio
async def test_sidebar_renders_one_airline_checkbox_per_distinct_airline(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=3)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, airline="Vueling"),
        _price("test|VY|2|2026-01-01T00:00:00", 110, airline="Vueling"),
        _price("test|IB|3|2026-01-01T00:00:00", 120, airline="Iberia"),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    assert len(re.findall(r'class="filter-airline"', sidebar)) == 2


@pytest.mark.asyncio
async def test_airline_checkbox_value_is_the_stable_identity_key(client):
    # Plan 024 phase 5 (F3/A6): the checkbox value is the stable identity key
    # ("VY", Vueling's mapped IATA code), not the display name ("Vueling") --
    # see the module-level note above. The visible label still shows the
    # pretty name.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    assert 'class="filter-airline" value="VY"' in sidebar
    assert "Vueling" in sidebar


@pytest.mark.asyncio
async def test_every_airline_checkbox_is_checked_by_default(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, airline="Vueling"),
        _price("test|IB|2|2026-01-01T00:00:00", 120, airline="Iberia"),
    ])

    response = await client.get("/trackers/1")
    inputs = re.findall(r'<input[^>]*class="filter-airline"[^>]*>', _sidebar(response.text))
    assert inputs and all("checked" in i for i in inputs)


@pytest.mark.asyncio
async def test_airline_count_reflects_flights_per_airline(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=3)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, airline="Vueling"),
        _price("test|VY|2|2026-01-01T00:00:00", 110, airline="Vueling"),
        _price("test|IB|3|2026-01-01T00:00:00", 120, airline="Iberia"),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    assert "(2)" in sidebar  # Vueling
    assert "(1)" in sidebar  # Iberia


@pytest.mark.asyncio
async def test_airline_best_price_is_min_within_airline(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 120, airline="Vueling"),
        _price("test|VY|2|2026-01-01T00:00:00", 90, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    assert "€90" in sidebar
    assert "120.00" not in sidebar


@pytest.mark.asyncio
async def test_airlines_sorted_by_best_price_ascending(client):
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|IB|1|2026-01-01T00:00:00", 200, airline="Iberia"),
        _price("test|VY|2|2026-01-01T00:00:00", 90, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    # Plan 024 phase 5: checkbox value is the identity key (IATA code for a
    # mapped carrier), not the display name -- see the note above.
    assert sidebar.index('value="VY"') < sidebar.index('value="IB"')


@pytest.mark.asyncio
async def test_duplicate_airline_deduped_to_single_entry(client):
    # FAILURE-MODE / off-by-one: two flights, same airline -> exactly one checkbox.
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|1|2026-01-01T00:00:00", 100, airline="Vueling"),
        _price("test|VY|2|2026-01-01T00:00:00", 110, airline="Vueling"),
    ])

    response = await client.get("/trackers/1")
    assert len(re.findall(r'class="filter-airline"', _sidebar(response.text))) == 1


@pytest.mark.asyncio
async def test_null_airline_renders_unknown_label_in_sidebar(client):
    # FAILURE-MODE: a null-airline flight gets an empty-value checkbox labeled "Unknown".
    from backend.db import create_snapshot, insert_flight_prices
    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap["id"], 1, [
        _price("test|VY|6201|2026-01-01T00:00:00", 100, airline=None),
    ])

    response = await client.get("/trackers/1")
    sidebar = _sidebar(response.text)
    assert 'class="filter-airline" value=""' in sidebar
    assert "Unknown" in sidebar


@pytest.mark.asyncio
async def test_no_airline_checkbox_when_no_snapshot(client):
    # EDGE: unsearched tracker has no sidebar at all -> no airline checkboxes, no crash.
    await _make_tracker(client)
    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert 'class="filter-airline"' not in response.text


# ---------------------------------------------------------------------------
# Plan 024 phase 5 (F3/A6) — checkbox identity is stable across blend composition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_airline_checkbox_value_is_byte_identical_across_blend_composition(client):
    # F3/A6: before this fix, the checkbox value was seeded from group["name"]
    # -- whichever variant's row happened to be first in price order -- so it
    # flipped between "LATAM AIRLINES" (Kayak-only cycle) and "LATAM" (once
    # google_flights also lists the flight). A persisted (localStorage)
    # unchecked-airline selection keyed on that value would silently re-check
    # itself the moment the display name changed. The fix makes the value the
    # stable _airline_identity key ("LA" for both variants), so it must be
    # byte-identical across both blend compositions.
    from backend.db import create_snapshot, insert_flight_prices

    await _make_tracker(client)

    kayak_only = await create_snapshot(1, results_count=1)
    await insert_flight_prices(kayak_only["id"], 1, [
        _price("la|2026-09-15T08:00:00|2026-09-15T10:00:00", 800,
               airline="LATAM AIRLINES", source="kayak"),
    ])
    response_1 = await client.get("/trackers/1")
    sidebar_1 = _sidebar(response_1.text)
    match_1 = re.search(r'class="filter-airline" value="([^"]*)"', sidebar_1)
    assert match_1 is not None, "no airline checkbox rendered in kayak-only cycle"

    blended = await create_snapshot(1, results_count=2)
    await insert_flight_prices(blended["id"], 1, [
        _price("la|2026-09-15T08:00:00|2026-09-15T10:00:00", 790,
               airline="LATAM", source="google_flights"),
        _price("la|2026-09-15T08:00:00|2026-09-15T10:00:00", 800,
               airline="LATAM AIRLINES", source="kayak"),
    ])
    response_2 = await client.get("/trackers/1")
    sidebar_2 = _sidebar(response_2.text)
    match_2 = re.search(r'class="filter-airline" value="([^"]*)"', sidebar_2)
    assert match_2 is not None, "no airline checkbox rendered in blended cycle"

    assert match_1.group(1) == match_2.group(1)


# ---------------------------------------------------------------------------
# Plan 024 phase 5 (A12/F10) — a source cannot appear twice in a merged row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merged_row_lists_each_source_once(client):
    # A12/F10: _group_duplicate_price_rows appended every matching row's
    # source unconditionally, so an unlikely-but-possible pair of rows from
    # the SAME source at the same flight_key/price (e.g. a dedupe upstream
    # that let one through twice) rendered "Kayak, Kayak" instead of "Kayak".
    from backend.db import create_snapshot, insert_flight_prices

    await _make_tracker(client)
    snap = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snap["id"], 1, [
        _price("la|2026-09-15T08:00:00|2026-09-15T10:00:00", 800, source="kayak"),
        _price("la|2026-09-15T08:00:00|2026-09-15T10:00:00", 800, source="kayak"),
    ])

    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "Kayak, Kayak" not in response.text


def test_group_duplicate_price_rows_dedupes_sources():
    from backend.pages import _group_duplicate_price_rows

    flight = {
        "flight_key": "la|2026-09-15T08:00:00|2026-09-15T10:00:00",
        "price": 800.0, "source": "kayak", "age_minutes": 5, "is_stale": False,
    }
    rows = [
        {"flight": dict(flight), "delta": {"type": "same"}},
        {"flight": dict(flight), "delta": {"type": "same"}},
    ]

    grouped = _group_duplicate_price_rows(rows)

    assert len(grouped) == 1
    assert grouped[0]["sources"] == ["kayak"]


# ---------------------------------------------------------------------------
# Plan 024 phase 5 (A11/F4) — _relative_minutes boundary table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("minutes,expected", [
    (0, "just now"),
    (1, "1m ago"),
    (59, "59m ago"),
    (60, "1h ago"),
    (1439, "23h ago"),
    (1440, "1d ago"),
])
def test_relative_minutes_boundaries(minutes, expected):
    # Counterpart: base.html::updateRelativeTimes() buckets the client-side
    # "Fetched" column with the identical mins -> hours -> days thresholds,
    # so a staleness badge rendered server-side reads the same as the
    # client-refreshed one next to it. If either side's thresholds drift,
    # this test and that function silently disagree -- check both when
    # changing one.
    from backend.pages import _relative_minutes

    assert _relative_minutes(minutes) == expected
