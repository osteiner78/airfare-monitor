import pytest
from unittest.mock import AsyncMock, patch


# NOTE: backend/sources/kayak.py does not exist yet (Phase 2 of plan 017).
# Every test below is expected to fail with ModuleNotFoundError until
# KayakSource is implemented -- that is the correct "fails for the right
# reason" state for a brand-new module (there is no existing behavior to
# assert against yet, unlike a modification to existing code).


def _sample_extraction():
    return [
        {
            "airline": "TAP AIR PORTUGAL",
            "flight_number": "TP 84+TP 934",
            "departure_time": "2026-08-21T00:45:00",
            "arrival_time": "2026-08-21T22:30:00",
            "duration_min": 1305,
            "stops": 1,
            "price": 785.0,
        }
    ]


def _sample_body():
    """Rendered body text that actually CONTAINS the sample extraction's price.

    search() grounds every extracted price against the rendered text before
    trusting it (plan 017 phase 2.7), so a stub body of "<rendered page text>"
    would now correctly cause the sample row to be dropped. Any test that
    expects search() to RETURN results must render text the price appears in.
    """
    return (
        "Cheapest\n€785\n26h 25m\nTAP AIR PORTUGAL\n1 stop\nGRU-ZRH\nSelect\n"
        "Best\n€1,204\n18h 10m\nSWISS\n1 stop\nGRU-ZRH\nSelect\n"
    )


# --- protocol conformance ---

async def test_kayak_source_satisfies_search_source_protocol():
    from backend.sources.kayak import KayakSource
    from backend.sources.base import SearchSource
    source = KayakSource()
    assert isinstance(source, SearchSource)


# --- URL construction (pure function, no browser/LLM needed) ---

async def test_build_url_includes_origin_destination_and_date():
    from backend.sources.kayak import KayakSource
    url = KayakSource._build_url("GRU", "ZRH", "2026-08-21", "EUR")
    assert "GRU-ZRH" in url
    assert "2026-08-21" in url


async def test_build_url_sorts_by_cheapest_price():
    from backend.sources.kayak import KayakSource
    url = KayakSource._build_url("GRU", "ZRH", "2026-08-21", "EUR")
    assert "price" in url.lower()


async def test_build_url_encodes_requested_currency():
    from backend.sources.kayak import KayakSource
    url_eur = KayakSource._build_url("GRU", "ZRH", "2026-08-21", "EUR")
    url_usd = KayakSource._build_url("GRU", "ZRH", "2026-08-21", "USD")
    assert url_eur != url_usd
    assert "EUR" in url_eur or "eur" in url_eur.lower()
    assert "USD" in url_usd or "usd" in url_usd.lower()


# --- bot-detection marker check (pure function) ---

async def test_looks_blocked_true_when_captcha_marker_present():
    from backend.sources.kayak import KayakSource
    assert KayakSource._looks_blocked("Please verify you are human to continue") is True


async def test_looks_blocked_false_for_normal_results_page():
    from backend.sources.kayak import KayakSource
    normal_text = "Cheapest $677 26h 25m\nTAP AIR PORTUGAL\n1 stop\nSelect"
    assert KayakSource._looks_blocked(normal_text) is False


async def test_looks_blocked_false_for_empty_string():
    from backend.sources.kayak import KayakSource
    assert KayakSource._looks_blocked("") is False


# Verbatim from the interstitial Kayak actually served on 2026-08-04 during
# Phase 6 live verification (.agent/reports/017-phase-6.md). The original
# marker list was written from guesses and matched NONE of this, so a real
# block was logged as "no flights found" -- indistinguishable from a route
# that genuinely has no flights, which made the phase's own block-rate
# sample uninterpretable.
_REAL_KAYAK_BLOCK_PAGE = (
    'If you are seeing this page, it means that KAYAK thinks you are a "bot," '
    "and the page you were trying to get to is only useful for humans.\n"
    "\n"
    "But I am not a bot! I'm human!\n"
)


async def test_looks_blocked_true_for_real_kayak_interstitial():
    from backend.sources.kayak import KayakSource
    assert KayakSource._looks_blocked(_REAL_KAYAK_BLOCK_PAGE) is True


async def test_looks_blocked_true_for_perimeterx_press_and_hold_challenge():
    from backend.sources.kayak import KayakSource
    text = "Pardon Our Interruption\nPress and Hold to confirm you are a human"
    assert KayakSource._looks_blocked(text) is True


async def test_looks_blocked_false_for_long_results_page_mentioning_humans():
    """False positives are as damaging as misses: a page wrongly called blocked
    returns [] without ever reaching extraction, silently dropping real prices.
    Markers must be specific to interstitial copy, not generic English."""
    from backend.sources.kayak import KayakSource
    text = (
        "Cheapest\n€785\n26h 25m\nTAP AIR PORTUGAL\n1 stop\nGRU-ZRH\nSelect\n"
        "Humanitarian fare available\nBot Air Charter\nSelect\n"
    )
    assert KayakSource._looks_blocked(text) is False


# --- search(): mapping extracted data to FlightResult ---

async def test_search_returns_flight_results_mapped_from_extraction():
    from backend.sources.kayak import KayakSource
    from backend.sources.base import FlightResult

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=_sample_extraction())):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert len(results) == 1
    assert isinstance(results[0], FlightResult)
    assert results[0].price == 785.0
    assert results[0].airline == "TAP AIR PORTUGAL"


async def test_search_sets_source_field_to_kayak_on_every_result():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=_sample_extraction())):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert all(r.source == "kayak" for r in results)


async def test_search_result_currency_matches_requested_currency():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=_sample_extraction())):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "USD", 5)

    assert all(r.currency == "USD" for r in results)


# --- failure modes ---

async def test_search_returns_empty_list_and_error_when_render_raises():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(side_effect=RuntimeError("navigation timeout"))):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert source.last_error_level == "ERROR"


async def test_search_returns_empty_list_and_warning_when_blocked_markers_detected():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    extract_mock = AsyncMock(return_value=_sample_extraction())
    with patch.object(source, "_render", AsyncMock(return_value="please verify you are human")), \
         patch.object(source, "_extract", extract_mock):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error_level == "WARNING"
    extract_mock.assert_not_called()  # never spend an LLM call parsing a CAPTCHA page


async def test_search_returns_empty_list_and_error_when_extraction_raises():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(side_effect=ValueError("malformed JSON from model"))):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert source.last_error_level == "ERROR"


async def test_search_returns_empty_list_and_warning_when_extraction_finds_no_flights():
    """A legitimate state -- the route has no flights that day -- not a code bug."""
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=[])):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error_level == "WARNING"


async def test_search_with_top_n_zero_returns_empty_list_without_rendering():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    render_mock = AsyncMock(return_value=_sample_body())
    with patch.object(source, "_render", render_mock):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 0)

    assert results == []
    render_mock.assert_not_called()


async def test_search_never_raises_for_unexpected_exception_type():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(side_effect=KeyError("unexpected"))):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []


# --- mapping edge cases ---

async def test_search_maps_result_with_missing_optional_fields_without_crashing():
    from backend.sources.kayak import KayakSource

    incomplete = [{
        "airline": "TAP AIR PORTUGAL",
        "flight_number": "TP 84",
        "departure_time": "2026-08-21T00:45:00",
        "arrival_time": "2026-08-21T22:30:00",
        "price": 785.0,
        # duration_min and stops deliberately omitted
    }]
    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=incomplete)):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert len(results) == 1
    assert results[0].duration_min is None


# --- grounding: extracted prices must exist in the rendered text ---
# An LLM reading a ~100KB text dump will occasionally invent or mis-associate a
# number. A hallucinated cheap price is PERMANENT damage here:
# historical_best_price is MIN over all rows and is never recomputed, and the
# bad price fires a notification on its way in. _validate is the cheap pure
# guard against that (plan 017 phase 2.7).

async def test_validate_drops_row_whose_price_is_absent_from_body_text():
    from backend.sources.kayak import KayakSource

    body = "Cheapest\n€785\n26h 25m\nTAP AIR PORTUGAL\nSelect\n"
    rows = [
        {"airline": "TAP", "flight_number": "TP 84", "price": 785.0},
        {"airline": "TAP", "flight_number": "TP 90", "price": 412.0},  # never rendered
    ]
    kept = KayakSource._validate(rows, body)
    assert [r["price"] for r in kept] == [785.0]


async def test_validate_keeps_row_whose_price_appears_thousands_separated():
    """Kayak renders four-digit fares as "€1,204" -- a naive `str(price) in body`
    check would drop every expensive itinerary as hallucinated."""
    from backend.sources.kayak import KayakSource

    body = "Best\n€1,204\n18h 10m\nSWISS\nSelect\n"
    kept = KayakSource._validate([{"airline": "SWISS", "flight_number": "LX 93", "price": 1204.0}], body)
    assert len(kept) == 1


async def test_validate_keeps_row_whose_price_uses_dot_thousands_separator():
    """Plan 018 switches the bundle to kayak.com.br / pt-BR, where four-digit
    fares render as "R$ 4.312" -- dot for thousands, comma for decimals, the
    inverse of en-US. _price_grounded's {str(n), f"{n:,}"} pair matches
    neither, so every expensive itinerary would be dropped as hallucinated:
    silent data loss that looks exactly like a successful empty extraction."""
    from backend.sources.kayak import KayakSource

    body = "TAP AIR PORTUGAL\nR$ 4.312\n10h 25m\nSelecionar\n"
    kept = KayakSource._validate([{"airline": "TAP", "flight_number": "TP 88", "price": 4312.0}], body)
    assert len(kept) == 1


async def test_validate_keeps_row_whose_price_uses_comma_decimals():
    from backend.sources.kayak import KayakSource

    body = "SWISS\nR$ 4.312,00\n18h 10m\nSelecionar\n"
    kept = KayakSource._validate([{"airline": "LX", "flight_number": "LX 93", "price": 4312.0}], body)
    assert len(kept) == 1


async def test_validate_drops_non_positive_price():
    from backend.sources.kayak import KayakSource

    body = "Cheapest\n€785\nTAP AIR PORTUGAL\nSelect\n0\n"
    rows = [
        {"airline": "TAP", "flight_number": "TP 84", "price": 785.0},
        {"airline": "TAP", "flight_number": "TP 90", "price": 0.0},
    ]
    kept = KayakSource._validate(rows, body)
    assert [r["price"] for r in kept] == [785.0]


async def test_validate_drops_price_wildly_outside_the_band_of_other_rows():
    """Guards the mis-association case: the price IS on the page (a phone
    number, a mileage total, an airport code run together) but is not a fare."""
    from backend.sources.kayak import KayakSource

    body = "€700\nSelect\n€750\nSelect\n€800\nSelect\n99999\n"
    rows = [
        {"airline": "A", "flight_number": "A 1", "price": 700.0},
        {"airline": "B", "flight_number": "B 2", "price": 750.0},
        {"airline": "C", "flight_number": "C 3", "price": 800.0},
        {"airline": "D", "flight_number": "D 4", "price": 99999.0},
    ]
    kept = KayakSource._validate(rows, body)
    assert [r["price"] for r in kept] == [700.0, 750.0, 800.0]


async def test_search_drops_hallucinated_price_not_present_in_rendered_text():
    """End-to-end: _validate must actually be wired into search(), not just
    exist as a testable helper."""
    from backend.sources.kayak import KayakSource

    hallucinated = _sample_extraction() + [{
        "airline": "TAP AIR PORTUGAL",
        "flight_number": "TP 90",
        "departure_time": "2026-08-21T06:00:00",
        "arrival_time": "2026-08-21T20:00:00",
        "duration_min": 840,
        "stops": 1,
        "price": 412.0,  # cheaper than anything on the page, and not on it
    }]

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=hallucinated)):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert [r.price for r in results] == [785.0]


async def test_search_warns_when_validation_drops_every_row():
    """A fully-hallucinated extraction must not look like a clean 'route has no
    flights' success. search_and_store only logs when last_error is set, and
    this project's observability is the system_logs table on /monitor -- the
    logger.warning calls inside _validate never reach it."""
    from backend.sources.kayak import KayakSource

    ungrounded = [{
        "airline": "TAP AIR PORTUGAL",
        "flight_number": "TP 90",
        "departure_time": "2026-08-21T06:00:00",
        "arrival_time": "2026-08-21T20:00:00",
        "duration_min": 840,
        "stops": 1,
        "price": 412.0,  # not present anywhere in _sample_body()
    }]

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=ungrounded)):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert source.last_error_level == "WARNING"


async def test_search_reports_dropped_row_count_when_some_rows_survive_validation():
    """A source quietly losing half its results to the grounding check is a
    signal about extraction quality -- and the input the reliability follow-up
    plan needs. Partial drops must still surface, without failing the run."""
    from backend.sources.kayak import KayakSource

    mixed = _sample_extraction() + [{
        "airline": "TAP AIR PORTUGAL",
        "flight_number": "TP 90",
        "departure_time": "2026-08-21T06:00:00",
        "arrival_time": "2026-08-21T20:00:00",
        "duration_min": 840,
        "stops": 1,
        "price": 412.0,
    }]

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract", AsyncMock(return_value=mixed)):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert [r.price for r in results] == [785.0]
    assert source.last_error is not None
    assert "1" in source.last_error  # how many rows were dropped
    assert source.last_error_level == "WARNING"


# --- secret hygiene ---

async def test_error_message_does_not_contain_api_key(monkeypatch):
    """last_error is written to system_logs and rendered on /monitor. LLM client
    exceptions can carry request context, so the key must be scrubbed before it
    reaches last_error. (Env var name must match whatever phase 2.11 settles on.)"""
    from backend.sources.kayak import KayakSource

    secret = "sk-do-not-log-me-0123456789"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_sample_body())), \
         patch.object(source, "_extract",
                      AsyncMock(side_effect=RuntimeError(f"401 unauthorized for key {secret}"))):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert secret not in source.last_error


# --- live search (requires network + Chromium + a real API key) ---

@pytest.mark.slow
async def test_real_kayak_search_returns_results_for_valid_route():
    from backend.sources.kayak import KayakSource
    from backend.sources.base import FlightResult

    source = KayakSource()
    results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)
    assert isinstance(results, list)
    if results:
        assert all(isinstance(r, FlightResult) for r in results)
        assert all(r.price > 0 for r in results)
        assert all(r.source == "kayak" for r in results)
