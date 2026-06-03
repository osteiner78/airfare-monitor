import pytest


TRACKER_FORM = {"origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15"}


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_contains_add_form(client):
    response = await client.get("/")
    assert "Add Route" in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_empty_state_when_no_trackers(client):
    response = await client.get("/")
    assert "No trackers yet" in response.text


@pytest.mark.asyncio
async def test_add_tracker_form_returns_200(client):
    response = await client.post("/", data=TRACKER_FORM)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_add_tracker_returns_html_with_route_info(client):
    response = await client.post("/", data=TRACKER_FORM)
    assert "GVA" in response.text
    assert "BCN" in response.text


@pytest.mark.asyncio
async def test_add_tracker_updates_tracker_list(client):
    await client.post("/", data=TRACKER_FORM)
    response = await client.get("/")
    assert "No trackers yet" not in response.text


@pytest.mark.asyncio
async def test_detail_page_returns_200_for_valid_tracker(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.get("/trackers/1")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_detail_page_returns_404_for_missing_tracker(client):
    response = await client.get("/trackers/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_page_contains_tracker_route(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.get("/trackers/1")
    assert "GVA" in response.text
    assert "BCN" in response.text


@pytest.mark.asyncio
async def test_search_now_returns_200(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.post("/trackers/1/search")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_search_now_returns_404_for_missing_tracker(client):
    response = await client.post("/trackers/999/search")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_returns_card_partial(client):
    await client.post("/api/trackers", json=TRACKER_FORM)
    response = await client.patch("/trackers/1/toggle")
    assert response.status_code == 200
    assert "tracker-card" in response.text


@pytest.mark.asyncio
async def test_toggle_returns_404_for_missing_tracker(client):
    response = await client.patch("/trackers/999/toggle")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_page_contains_chart_canvas_when_snapshot_exists(client):
    from backend.db import get_db_path, create_snapshot, insert_flight_prices
    import os
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
    }])
    response = await client.get("/trackers/1")
    assert response.status_code == 200
    assert "price-chart" in response.text


@pytest.mark.asyncio
async def test_detail_page_contains_results_table_when_snapshot_exists(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "results-table" in response.text


@pytest.mark.asyncio
async def test_detail_page_contains_booking_url_column(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "google.com/travel/flights" in response.text


@pytest.mark.asyncio
async def test_detail_page_does_not_embed_full_html_in_detail_content(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
    }])
    response = await client.post("/trackers/1/search")
    text = response.text
    assert text.count("<html") == 0


# --- Phase 2: results table logo ---

@pytest.mark.asyncio
async def test_results_table_renders_kiwi_logo_for_valid_code(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
        "source": "test",
        "price": 89.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "VY 6201",
        "departure_time": "2026-09-15T10:00:00",
        "arrival_time": "2026-09-15T11:15:00",
        "duration_min": 75,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "/airline-logo/VY" in response.text


@pytest.mark.asyncio
async def test_results_table_logo_alt_is_airline_name(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
        "source": "test",
        "price": 89.0,
        "currency": "EUR",
        "airline": "Vueling",
        "flight_number": "VY 6201",
        "departure_time": "2026-09-15T10:00:00",
        "arrival_time": "2026-09-15T11:15:00",
        "duration_min": 75,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'alt="Vueling"' in response.text


@pytest.mark.asyncio
async def test_results_table_falls_back_to_name_when_code_invalid(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|XX|123|2026-01-01T00:00:00",
        "source": "test",
        "price": 100.0,
        "currency": "EUR",
        "airline": "XX",
        "flight_number": "123",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120,
        "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "XX" in response.text
    assert "images.kiwi.com" not in response.text


# --- Phase 3: dashboard card logo ---

@pytest.mark.asyncio
async def test_dashboard_card_renders_logo_for_best_flight(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=2)
    await insert_flight_prices(snapshot["id"], 1, [
        {
            "flight_key": "test|Vueling|VY6201|2026-09-15T10:00:00",
            "source": "test",
            "price": 150.0,
            "currency": "EUR",
            "airline": "Vueling",
            "flight_number": "VY 6201",
        },
        {
            "flight_key": "test|Lufthansa|LH400|2026-09-15T08:00:00",
            "source": "test",
            "price": 120.0,
            "currency": "EUR",
            "airline": "Lufthansa",
            "flight_number": "LH 400",
        },
    ])
    response = await client.get("/")
    assert "/airline-logo/LH" in response.text


# --- Plan 009: results-table row colors match chart line colors ---

@pytest.mark.asyncio
async def test_charted_row_carries_its_chart_color(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert "--row-color: #4a90d9" in response.text


@pytest.mark.asyncio
async def test_charted_row_has_flight_key_data_attribute(client):
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'data-flight-key="test|VY|6201|2026-01-01T00:00:00"' in response.text


@pytest.mark.asyncio
async def test_missing_row_has_no_row_color(client):
    # snapshot 1 has flight A; snapshot 2 replaces it with flight B, so A becomes
    # a "missing" row. Only B is charted, so exactly one row may be colored.
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json=TRACKER_FORM)
    snap1 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap1["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": 100.0, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
        "departure_time": "2026-01-01T10:00:00",
        "arrival_time": "2026-01-01T12:00:00",
        "duration_min": 120, "stops": 0,
    }])
    snap2 = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snap2["id"], 1, [{
        "flight_key": "test|LH|400|2026-01-02T00:00:00",
        "source": "test", "price": 120.0, "currency": "EUR",
        "airline": "Lufthansa", "flight_number": "LH 400",
        "departure_time": "2026-01-02T08:00:00",
        "arrival_time": "2026-01-02T10:00:00",
        "duration_min": 120, "stops": 0,
    }])
    response = await client.get("/trackers/1")
    assert 'data-flight-key="test|VY|6201|2026-01-01T00:00:00"' in response.text
    assert response.text.count("row-colored") == 1


# === Plan 012: tracker card polish ===
# Fail-first tests pinning the redesigned card (labels, date, one-way tag) and
# the tightened currency symbol. They fail against the current implementation.

async def _seed_card(client, depart_date="2026-09-15", price=100.0):
    """One tracker + one snapshot + one priced flight, so the dashboard card
    renders a best price and an all-time best."""
    from backend.db import create_snapshot, insert_flight_prices
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": depart_date,
    })
    snapshot = await create_snapshot(1, results_count=1)
    await insert_flight_prices(snapshot["id"], 1, [{
        "flight_key": "test|VY|6201|2026-01-01T00:00:00",
        "source": "test", "price": price, "currency": "EUR",
        "airline": "Vueling", "flight_number": "VY 6201",
    }])


# --- Phase 2: labels, date, one-way ---

@pytest.mark.asyncio
async def test_card_label_drops_word_price(client):
    await _seed_card(client)
    text = (await client.get("/")).text
    assert "Current best price" not in text
    assert "All-time best price" not in text
    assert "Current best" in text
    assert "All-time best" in text


@pytest.mark.asyncio
async def test_card_date_includes_weekday(client):
    import datetime
    await _seed_card(client, depart_date="2026-07-29")
    text = (await client.get("/")).text
    weekday = datetime.date(2026, 7, 29).strftime("%a")   # e.g. "Wed"
    assert weekday in text
    assert "July 29" not in text   # the old month-first format is gone


@pytest.mark.asyncio
async def test_card_shows_one_way_tag(client):
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": "2026-09-15",
    })
    text = (await client.get("/")).text
    assert "one-way" in text


def test_format_card_date_filter_unit():
    import datetime
    from backend.pages import _format_card_date
    result = _format_card_date("2026-07-29")
    weekday = datetime.date(2026, 7, 29).strftime("%a")
    assert result.startswith(weekday)
    assert "29" in result
    assert "Jul" in result
    # malformed input passes through unchanged (mirrors _format_date)
    assert _format_card_date("not-a-date") == "not-a-date"


# --- Phase 3: currency symbol spacing ---

def test_currency_symbol_eur_has_no_trailing_space():
    from backend.pages import _env
    assert _env.filters["currency_symbol"]("EUR") == "€"


def test_currency_symbol_chf_keeps_space():
    from backend.pages import _env
    assert _env.filters["currency_symbol"]("CHF") == "CHF "


def test_unknown_currency_still_separated():
    from backend.pages import _env
    assert _env.filters["currency_symbol"]("XYZ").endswith(" ")


@pytest.mark.asyncio
async def test_card_price_has_no_space_after_symbol(client):
    await _seed_card(client, price=100.0)
    text = (await client.get("/")).text
    assert "€100" in text
    assert "€ 100" not in text


# === Plan 013: 2-column price panel with color-matched y-rail ===
# Fail-first — pins the rail layout, the removed chart text labels, and the
# at-all-time-low combined state.

async def _seed_history(client, prices, depart_date="2026-09-15"):
    """A tracker with one snapshot per price, forced to strictly increasing
    timestamps so the latest snapshot (and the series order) is deterministic."""
    import aiosqlite
    from backend.db import create_snapshot, insert_flight_prices, get_db_path
    await client.post("/api/trackers", json={
        "origin": "GVA", "destination": "BCN", "depart_date": depart_date,
    })
    for i, p in enumerate(prices):
        snap = await create_snapshot(1, results_count=1)
        ts = f"2026-01-{i + 1:02d} 12:00:00"
        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                "UPDATE snapshots SET searched_at = ? WHERE id = ?", (ts, snap["id"])
            )
            await db.commit()
        await insert_flight_prices(snap["id"], 1, [{
            "flight_key": f"test|VY|{i}|2026-01-{i + 1:02d}T00:00:00",
            "source": "test", "price": float(p), "currency": "EUR",
            "airline": "Vueling", "flight_number": "VY 6201",
        }])


@pytest.mark.asyncio
async def test_card_has_no_spark_text_labels(client):
    await _seed_history(client, [100, 110])
    text = (await client.get("/")).text
    assert "spark-price-label" not in text
    assert "spark-low-label" not in text


@pytest.mark.asyncio
async def test_card_renders_price_rail(client):
    await _seed_history(client, [80, 100])   # current 100 > all-time low 80
    text = (await client.get("/")).text
    assert "price-rail" in text
    assert "rail-current" in text


@pytest.mark.asyncio
async def test_card_keeps_best_price_class_for_filter_js(client):
    # non-regression: dashboard applyFilteredPrices overwrites .best-price and
    # toggles .filtered-tag — both must survive the refactor in every branch.
    await _seed_history(client, [80, 100])
    text = (await client.get("/")).text
    assert "best-price" in text
    assert "filtered-tag" in text


@pytest.mark.asyncio
async def test_card_at_all_time_low_shows_combined_stat(client):
    await _seed_history(client, [100, 80])   # latest snapshot is the cheapest ever
    text = (await client.get("/")).text
    assert "rail-combined" in text
    assert "all-time best" in text.lower()


@pytest.mark.asyncio
async def test_card_not_at_all_time_low_shows_two_rail_stats(client):
    await _seed_history(client, [80, 100])
    text = (await client.get("/")).text
    assert "rail-current" in text
    assert "rail-alltime" in text
    assert "rail-combined" not in text


@pytest.mark.asyncio
async def test_card_without_history_uses_fallback(client):
    await _seed_history(client, [120])       # single snapshot → no sparkline
    text = (await client.get("/")).text
    assert "panel-fallback" in text
    assert "price-rail" not in text
    assert "best-price" in text


# === Plan 014: Geist font, single trend chip, de-duplicated logo ===
# Fail-first — pins the `_primary_delta` selector, the trend chip, the removed
# evo-strip, the single airline logo, and the Geist font swap.

# --- Phase 1: _primary_delta selector (pure) ---

def test_primary_delta_prefers_3h():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": {"type": "down", "amount": 3.0},
        "delta_24h": {"type": "up", "amount": 5.0},
        "delta_creation": {"type": "up", "amount": 2.0},
    })
    assert pd["period"] == "3h"
    assert pd["type"] == "down"


def test_primary_delta_falls_back_to_24h():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": None,
        "delta_24h": {"type": "up", "amount": 5.0},
        "delta_creation": {"type": "down", "amount": 2.0},
    })
    assert pd["period"] == "24h"


def test_primary_delta_falls_back_to_start():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": None,
        "delta_24h": None,
        "delta_creation": {"type": "down", "amount": 2.0},
    })
    assert pd["period"] == "start"


def test_primary_delta_skips_same():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": {"type": "same"},
        "delta_24h": {"type": "down", "amount": 4.0},
        "delta_creation": {"type": "up", "amount": 1.0},
    })
    assert pd["period"] == "24h"
    assert pd["type"] == "down"


def test_primary_delta_none_when_no_movement():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": {"type": "same"},
        "delta_24h": None,
        "delta_creation": {"type": "same"},
    })
    assert pd is None


def test_primary_delta_carries_type_and_amount():
    from backend.pages import _primary_delta
    pd = _primary_delta({
        "delta_3h": None,
        "delta_24h": None,
        "delta_creation": {"type": "up", "amount": 7.5},
    })
    assert pd["type"] == "up"
    assert pd["amount"] == 7.5
    assert pd["period"] == "start"


# --- Phase 2: card markup / CSS (chip, evo-strip removal, logo, font) ---

@pytest.mark.asyncio
async def test_card_has_no_evo_strip(client):
    await _seed_history(client, [80, 100])
    text = (await client.get("/")).text
    assert "evo-strip" not in text


@pytest.mark.asyncio
async def test_card_shows_trend_chip_when_moved(client):
    # current (110) differs from creation (100) → a movement chip should render
    await _seed_history(client, [100, 110])
    text = (await client.get("/")).text
    assert "trend-chip" in text


@pytest.mark.asyncio
async def test_card_no_trend_chip_when_flat(client):
    # price never moved → no chip
    await _seed_history(client, [100, 100])
    text = (await client.get("/")).text
    assert "trend-chip" not in text


@pytest.mark.asyncio
async def test_card_alltime_has_no_logo(client):
    # two-stat card (current 100 > all-time low 80), single airline (VY):
    # the logo must render exactly once (on CURRENT only).
    await _seed_history(client, [80, 100])
    text = (await client.get("/")).text
    assert text.count("/airline-logo/VY") == 1


@pytest.mark.asyncio
async def test_card_uses_geist_font(client):
    text = (await client.get("/")).text
    assert "Geist" in text


@pytest.mark.asyncio
async def test_spark_svg_uses_preserve_aspect_ratio_none(client):
    # The sparkline SVG must carry preserveAspectRatio="none" so the line/area
    # fill the container. Dots are CSS elements and are not affected by this.
    await _seed_history(client, [80, 100])
    text = (await client.get("/")).text
    assert 'preserveAspectRatio="none"' in text
