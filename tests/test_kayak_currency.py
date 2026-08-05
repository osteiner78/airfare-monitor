"""Tests for plan 019 Phase 1 — never store a price whose currency is unverified.

Plan 017 Decision 7 assumed `?currency=EUR` in the search URL was enough and
that no conversion math would be needed downstream. Plan 018's live run
falsified it: all 9 captured bodies in `data/kayak-samples/` show
`English / $ / United States dollar` and $-prefixed prices, while
`_map_result` stamps the *tracker's* currency onto every row. Promoting that
would write USD values labelled EUR.

Verifying without forcing is not a fix either -- Kayak rows in USD sitting
beside Google rows in EUR would make `get_tracker_summaries`'s
`best_price = MIN(fp.price)` a comparison across currencies, which is a more
dangerous kind of wrong than a mislabelled row. Hence: attempt to force,
read back what was served, and refuse on disagreement.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.

Everything here is NEW-BEHAVIOR: before Phase 1 these fail with ImportError
(`_page_currency`) or because `search()` returns rows regardless of what
currency the page was actually served in.
"""

from unittest.mock import AsyncMock, patch

import pytest

# Verbatim header chrome from data/kayak-samples/20260805T060352.529333.txt
# (lines 29-35). The active currency is an adjacent symbol/name pair; the
# selector elsewhere on the page lists other currencies, so a naive substring
# search for "Euro" would find one on this very page. Read the ACTIVE pair.
_USD_BODY = (
    "NEW\nTrips\nEnglish\n$\nUnited States dollar\nFeedback\n75% complete.\n"
    "12:30 am – 5:40 pm\nRoyal Air Maroc\n1 stop\nCMN\n13h 10m\nGRU\n-\nLIS\n"
    "1\n0\n$554\nEconomy Cabin\nSelect\n"
)

_EUR_BODY = _USD_BODY.replace("$\nUnited States dollar", "€\nEuro").replace("$554", "€554")

_NO_CURRENCY_BODY = (
    "Trips\nEnglish\nFeedback\n"
    "12:30 am – 5:40 pm\nRoyal Air Maroc\n1 stop\n13h 10m\n554\nSelect\n"
)


def _extraction():
    return [{
        "airline": "Royal Air Maroc",
        "flight_number": "",
        "departure_time": "2026-10-04T00:30:00",
        "arrival_time": "2026-10-04T17:40:00",
        "duration_min": 790,
        "stops": 1,
        "price": 554.0,
    }]


# --- reading what was actually served (pure) ---

async def test_page_currency_reads_usd_from_a_real_captured_body():
    from backend.sources.kayak import _page_currency
    assert _page_currency(_USD_BODY) == "USD"


async def test_page_currency_reads_eur_when_that_is_what_was_served():
    from backend.sources.kayak import _page_currency
    assert _page_currency(_EUR_BODY) == "EUR"


async def test_page_currency_returns_none_when_no_currency_marker_present():
    """Unreadable is not the same as matching -- see the refusal test below."""
    from backend.sources.kayak import _page_currency
    assert _page_currency(_NO_CURRENCY_BODY) is None


# --- refusing what we cannot vouch for ---

async def test_search_refuses_result_when_page_currency_differs_from_requested():
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_USD_BODY)), \
         patch.object(source, "_extract", AsyncMock(return_value=_extraction())):
        results = await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert "USD" in source.last_error and "EUR" in source.last_error
    assert source.last_error_level == "WARNING"


async def test_search_does_not_call_extract_when_currency_mismatches():
    """Same cost-ordering rule as the block check: never spend an LLM call on
    a page whose result is already going to be refused."""
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    extract_mock = AsyncMock(return_value=_extraction())
    with patch.object(source, "_render", AsyncMock(return_value=_USD_BODY)), \
         patch.object(source, "_extract", extract_mock):
        await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    extract_mock.assert_not_called()


async def test_search_refuses_result_when_page_currency_is_unreadable():
    """An unverifiable currency is not a usable one. Storing the tracker's
    requested currency and hoping would reintroduce exactly the defect this
    check exists to prevent."""
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_NO_CURRENCY_BODY)), \
         patch.object(source, "_extract", AsyncMock(return_value=_extraction())):
        results = await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    assert results == []
    assert source.last_error_level == "WARNING"


async def test_search_proceeds_when_page_currency_matches_requested():
    """NON-REGRESSION for the happy path: verification must not become a
    blanket refusal."""
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_EUR_BODY)), \
         patch.object(source, "_extract", AsyncMock(return_value=_extraction())):
        results = await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    assert len(results) == 1
    assert results[0].currency == "EUR"
    assert results[0].price == 554.0


async def test_search_stores_no_row_it_cannot_vouch_for_even_when_extraction_succeeds():
    """The defect in one sentence: a perfectly good extraction from a page
    served in the wrong currency must produce zero stored rows, not rows
    labelled with a currency they are not denominated in."""
    from backend.sources.kayak import KayakSource

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_USD_BODY)), \
         patch.object(source, "_extract", AsyncMock(return_value=_extraction() * 5)):
        results = await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    assert results == []
