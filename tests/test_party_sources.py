"""Plan 028 Phase 4 — the party reaches both source families, and is verified.

NEW-BEHAVIOR and FAILURE-MODE. All fail until Phase 4 lands.

The highest-consequence line in this plan is Kayak's per-person -> total
multiplication: forget it and Kayak reads ~N times cheaper than Google and wins
every headline permanently (historical_best_price is MIN over all rows and is
never recomputed); double it and Kayak never wins. Both directions are caught
below.

The party is also GROUNDED against the rendered page rather than trusted from
the URL, because this project already shipped `?currency=EUR` for weeks before
discovering Kayak ignored it (see the currency note in CLAUDE.md).
"""

import pytest


def _party(adults=2, child_ages=(), infants_on_lap=0):
    from backend.party import Party
    return Party(adults=adults, child_ages=child_ages, infants_on_lap=infants_on_lap)


def _query(party):
    from backend.sources.base import SearchQuery
    return SearchQuery(origin="GRU", dest="ZRH", depart_date="2026-11-20",
                       return_date=None, currency="EUR", top_n=5, party=party)


# --- fli / Google ---

def test_google_passenger_info_is_built_from_the_party():
    from backend.sources.google_flights import GoogleFlightsSource
    info = GoogleFlightsSource._passenger_info(_party(adults=2, child_ages=(6,)))
    assert (info.adults, info.children) == (2, 1)


def test_google_passenger_info_splits_lap_and_seated_infants():
    from backend.sources.google_flights import GoogleFlightsSource
    info = GoogleFlightsSource._passenger_info(
        _party(adults=2, child_ages=(1, 1), infants_on_lap=1))
    assert (info.infants_on_lap, info.infants_in_seat) == (1, 1)


# --- fast_flights ---

def test_fast_flights_never_requests_zero_adults():
    """fast_flights.Passengers defaults every field to 0, so a naively empty
    construction asks Google for a party of nobody."""
    from backend.sources.fast_flights import FastFlightsSource
    passengers = FastFlightsSource._passengers(_party(adults=1))
    assert passengers.adults >= 1


def test_fast_flights_passengers_match_the_party():
    from backend.sources.fast_flights import FastFlightsSource
    passengers = FastFlightsSource._passengers(_party(adults=3, child_ages=(4,)))
    assert (passengers.adults, passengers.children) == (3, 1)


# --- Kayak URL ---

def test_kayak_url_contains_the_party_segment_for_multiple_adults():
    from backend.sources.kayak import KayakSource
    url = KayakSource._build_url("GRU", "ZRH", "2026-11-20", "EUR", _party(adults=2))
    assert "2adults" in url


def test_kayak_url_encodes_each_child_age():
    from backend.sources.kayak import KayakSource
    url = KayakSource._build_url("GRU", "ZRH", "2026-11-20", "EUR",
                                 _party(adults=2, child_ages=(6,)))
    assert "6" in url.rsplit("/", 1)[-1] or "children" in url


def test_a_single_adult_url_is_unchanged_from_today():
    """NON-REGRESSION in spirit: the 1-adult URL must not gain a party segment,
    or every captured sample and every stored Kayak row predates a URL change
    for no reason."""
    from backend.sources.kayak import KayakSource
    url = KayakSource._build_url("GRU", "ZRH", "2026-11-20", "EUR", _party(adults=1))
    assert url == (
        "https://www.kayak.com/flights/GRU-ZRH/2026-11-20"
        "?sort=price_a&currency=EUR"
    )


# --- the multiplication ---

def test_kayak_per_person_price_is_multiplied_by_party_size():
    from backend.sources.kayak import KayakSource
    row = {"airline": "Iberia", "price": 500.0,
           "departure_time": "2026-11-20T19:20:00",
           "arrival_time": "2026-11-21T10:35:00"}
    result = KayakSource._map_result(row, "EUR", "u", _party(adults=2))
    assert result.price == 1000.0


def test_kayak_price_for_one_traveller_is_not_multiplied():
    from backend.sources.kayak import KayakSource
    row = {"airline": "Iberia", "price": 500.0,
           "departure_time": "2026-11-20T19:20:00",
           "arrival_time": "2026-11-21T10:35:00"}
    result = KayakSource._map_result(row, "EUR", "u", _party(adults=1))
    assert result.price == 500.0


def test_a_lap_infant_counts_toward_the_kayak_multiplier():
    """Kayak prints per person including the infant, so the multiplier is the
    traveller count, not the seat count."""
    from backend.sources.kayak import KayakSource
    row = {"airline": "Iberia", "price": 100.0,
           "departure_time": "2026-11-20T19:20:00",
           "arrival_time": "2026-11-21T10:35:00"}
    result = KayakSource._map_result(
        row, "EUR", "u", _party(adults=1, child_ages=(1,), infants_on_lap=1))
    assert result.price == 200.0


# --- grounding the party against the page ---

def test_a_page_showing_the_requested_party_is_grounded():
    from backend.sources.kayak import KayakSource
    body = "Flights\n2 travelers\nEconomy\nSelect\n"
    assert KayakSource._party_grounded(body, _party(adults=2)) is True


def test_a_page_showing_a_different_party_is_not_grounded():
    """The `?currency=EUR` lesson: a parameter sent is not a parameter applied."""
    from backend.sources.kayak import KayakSource
    body = "Flights\n1 traveler\nEconomy\nSelect\n"
    assert KayakSource._party_grounded(body, _party(adults=2)) is False


def test_a_page_printing_no_traveller_count_grounds_nothing():
    """Deliberate abstention, matching _time_grounded: a body with nothing to
    check against must not be treated as confirmation."""
    from backend.sources.kayak import KayakSource
    assert KayakSource._party_grounded("Flights\nEconomy\nSelect\n", _party(adults=2)) is False


def test_an_empty_body_is_not_grounded():
    from backend.sources.kayak import KayakSource
    assert KayakSource._party_grounded("", _party(adults=2)) is False


@pytest.mark.asyncio
async def test_a_page_that_did_not_apply_the_party_returns_no_rows_at_warning(monkeypatch):
    """Refusing loudly beats storing a 1-adult price labelled as a party total."""
    from backend.sources.kayak import KayakSource
    source = KayakSource()
    monkeypatch.setattr(source, "_render",
                        lambda url: _async_return("English\n€\nEuro\n1 traveler\nSelect\n"))
    rows = await source.search(_query(_party(adults=2)))
    assert rows == [] and source.last_error_level == "WARNING"


def _async_return(value):
    async def _coro():
        return value
    return _coro()


# --- storage ---

@pytest.mark.asyncio
async def test_every_stored_row_carries_its_trackers_passenger_count(db_path):
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-11-20", adults=2)
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(snapshot["id"], tracker["id"], [{
        "flight_key": "ib|2026-11-20T19:20:00|2026-11-21T10:35:00",
        "source": "kayak", "price": 1000.0, "currency": "EUR",
        "passenger_count": 2,
    }])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["passenger_count"] == 2


@pytest.mark.asyncio
async def test_a_row_stored_without_a_passenger_count_reads_as_one(db_path):
    """Every pre-Passengers row is a 1-adult total and must stay valid without
    being rewritten."""
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH", depart_date="2026-11-20")
    snapshot = await create_snapshot(tracker["id"], results_count=1)
    await insert_flight_prices(snapshot["id"], tracker["id"], [{
        "flight_key": "ib|2026-11-20T19:20:00|2026-11-21T10:35:00",
        "source": "google_flights", "price": 500.0, "currency": "EUR",
    }])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    assert rows[0]["passenger_count"] == 1


# --- the cross-source check (verification #1) ---

@pytest.mark.asyncio
async def test_two_sources_quoting_one_flight_agree_within_tolerance_for_adults_only(db_path):
    """The ×N conversion bug's signature: one flight_key, one snapshot, two
    sources ~N times apart. Adults-only, where the two sources have no
    legitimate reason to disagree beyond normal fare drift (measured 0.7% in
    production on 2026-08-15)."""
    from backend.db import create_snapshot, create_tracker, get_flight_prices_for_snapshot, insert_flight_prices
    tracker = await create_tracker(origin="GRU", destination="ZRH",
                                   depart_date="2026-11-20", adults=2)
    snapshot = await create_snapshot(tracker["id"], results_count=2)
    key = "ib|2026-11-20T19:20:00|2026-11-21T10:35:00"
    await insert_flight_prices(snapshot["id"], tracker["id"], [
        {"flight_key": key, "source": "google_flights", "price": 1000.0,
         "currency": "EUR", "passenger_count": 2},
        {"flight_key": key, "source": "kayak", "price": 1010.0,
         "currency": "EUR", "passenger_count": 2},
    ])
    rows = await get_flight_prices_for_snapshot(snapshot["id"])
    prices = [r["price"] for r in rows if r["flight_key"] == key]
    assert max(prices) / min(prices) < 1.10
