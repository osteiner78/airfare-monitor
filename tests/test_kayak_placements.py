"""Tests for plan 020 — keep adverts out of the price data, ground the airline.

Plan 019 Phase 4 promoted Kayak and the first live cycle stored an advert's
price as a flight: the model took €806 out of an Expedia paid placement and
welded it onto the times and carrier of the row printed immediately below,
producing `arajet|2026-08-21T03:50:00|2026-08-22T22:20:00 @ €806` — an
itinerary that does not exist at that price. The genuine row for the same
itinerary was stored correctly at €654.

Both existing guards pass it by construction: `_price_grounded` asks whether
€806 is printed on the page (it is, three times inside the advert) and
`_time_grounded` asks whether the clock times are printed (they are, on the
real row). Neither asks whether a value *belongs to* the row it was attached
to. Removing the advert text is the guarantee a prompt instruction would only
request.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.

Everything here is NEW-BEHAVIOR: before plan 020 these fail with ImportError
(`_strip_placements`, `_airline_grounded`) or because `search()` happily
returns the advert price.
"""

from unittest.mock import AsyncMock, patch

import pytest

_DISCLOSURE = (
    "Book your flight to unlock more savings Members can save up to 30% when "
    "they add a hotel to their flight. This is a paid placement from Expedia. "
    "You're seeing it because of its relevance to your search and the "
    "advertiser's bid. €806 View Deal"
)

# Verbatim shape of data/kayak-samples/20260806T012940.952907.txt lines
# 112-137: the sort-summary tabs, the Expedia placement, then the first
# genuine result. Note €806 occurs THREE times inside the block -- on the
# disclosure line itself and twice standalone -- so dropping the disclosure
# line alone leaves the price behind for the model to find.
_EUR_HEADER = "English\n€\nEuro\nFeedback\n"

_BODY_WITH_PLACEMENT = (
    _EUR_HEADER +
    "Best\n"
    "€654 • 37h 30m\n"
    "Quickest\n"
    "€1,146 • 11h 15m\n"
    "Other sort\n"
    + _DISCLOSURE + "\n"
    "Book your flight to unlock more savings\n"
    "Members can save up to 30% when they add a hotel to their flight.\n"
    "€806\n"
    "1 stop\n"
    "€1,228\n"
    "nonstop\n"
    "Expedia\n"
    "|\n"
    "Ad\n"
    "€806\n"
    "Economy\n"
    "View Deal\n"
    "Go to next result\n"
    "Go to price section\n"
    "Go to result details\n"
    "Self-transfer hack\n"
    "3:50 am – 10:20 pm+1\n"
    "Arajet, Iberia\n"
    "3 stops\n"
    "37h 30m\n"
    "GRU\n-\nZRH\n"
    "€654\n"
    "Economy Cabin + Basic + Economy\n"
    "Select\n"
)

# The same page carries further placements lower down, for car hire rather
# than flights -- those carry no flight price but must still not survive, or
# the model can pull a rental figure into a fare.
_CAR_PLACEMENT = (
    "Cheap car rental in Zurich Flexible, low-cost car rentals with Budget: "
    "travel freely, change plans anytime, save money. This is a paid placement "
    "from Budget. You're seeing it because of its relevance to your search and "
    "the advertiser's bid. View Deal\n"
    "Budget\n"
    "|\n"
    "Ad\n"
    "€39\n"
    "View Deal\n"
)

_CLEAN_BODY = (
    _EUR_HEADER +
    "Best\n"
    "€654 • 37h 30m\n"
    "3:50 am – 10:20 pm+1\n"
    "Arajet, Iberia\n"
    "3 stops\n"
    "37h 30m\n"
    "€654\n"
    "Select\n"
)


# --- Phase 1: stripping paid placements ---

async def test_strips_the_expedia_placement_block_from_a_real_captured_body():
    from backend.sources.kayak import _strip_placements
    stripped = _strip_placements(_BODY_WITH_PLACEMENT)
    assert "paid placement" not in stripped
    assert "Expedia" not in stripped


async def test_placement_price_does_not_survive_stripping():
    """The defect in one assertion. €806 appears three times inside the block
    -- inline on the disclosure line and twice standalone -- so a line-level
    filter is not enough; the whole span has to go."""
    from backend.sources.kayak import _strip_placements
    assert _BODY_WITH_PLACEMENT.count("€806") == 3
    assert "€806" not in _strip_placements(_BODY_WITH_PLACEMENT)


async def test_genuine_result_rows_survive_stripping():
    """A filter that eats real results would be a worse bug than the one it
    fixes -- it would silently lower coverage with no error anywhere."""
    from backend.sources.kayak import _strip_placements
    stripped = _strip_placements(_BODY_WITH_PLACEMENT)
    assert "€654" in stripped
    assert "Arajet, Iberia" in stripped
    assert "3:50 am – 10:20 pm+1" in stripped
    assert stripped.count("Select") == _BODY_WITH_PLACEMENT.count("Select")


async def test_strips_every_placement_not_just_the_first():
    from backend.sources.kayak import _strip_placements
    stripped = _strip_placements(_BODY_WITH_PLACEMENT + _CAR_PLACEMENT)
    assert "paid placement" not in stripped
    assert "Budget" not in stripped
    assert "€39" not in stripped
    assert "€654" in stripped


async def test_body_without_placements_is_returned_unchanged():
    from backend.sources.kayak import _strip_placements
    assert _strip_placements(_CLEAN_BODY) == _CLEAN_BODY


async def test_search_does_not_extract_a_placement_price():
    """End-to-end: the model is handed the stripped body, so it cannot weld an
    advert price onto the itinerary below it. Mirrors what actually happened on
    2026-08-06 -- the model returned both the real €654 row and a fabricated
    €806 one sharing its times."""
    from backend.sources.kayak import KayakSource

    async def _fake_extract(body_text, top_n, depart_date=None):
        rows = [{
            "airline": "Multiple airlines", "flight_number": "",
            "departure_time": "2026-08-21T03:50:00",
            "arrival_time": "2026-08-22T22:20:00",
            "duration_min": 2250, "stops": 3, "price": 654.0,
        }]
        if "€806" in body_text:            # only possible if stripping failed
            rows.append({
                "airline": "Arajet", "flight_number": "",
                "departure_time": "2026-08-21T03:50:00",
                "arrival_time": "2026-08-22T22:20:00",
                "duration_min": 2250, "stops": 3, "price": 806.0,
            })
        return rows

    source = KayakSource()
    with patch.object(source, "_render", AsyncMock(return_value=_BODY_WITH_PLACEMENT)), \
         patch.object(source, "_extract", AsyncMock(side_effect=_fake_extract)):
        results = await source.search("GRU", "ZRH", "2026-08-21", None, "EUR", 5)

    assert [r.price for r in results] == [654.0]


# --- Phase 2: grounding the airline component of the identity ---

async def test_validate_drops_row_whose_airline_is_absent_from_rendered_text():
    """flight_key is airline|departure|arrival. Price and both times are
    grounded against the page; the airline was not, leaving one third of the
    identity able to be fabricated -- and a fabricated airline forks a flight
    exactly the way a misread time does."""
    from backend.sources.kayak import KayakSource

    rows = [{"airline": "Iberia", "flight_number": "", "price": 654.0,
             "departure_time": "2026-08-21T03:50:00",
             "arrival_time": "2026-08-22T22:20:00"},
            {"airline": "Ryanair", "flight_number": "", "price": 654.0,
             "departure_time": "2026-08-21T03:50:00",
             "arrival_time": "2026-08-22T22:20:00"}]
    body = "Iberia\n3:50 am – 10:20 pm+1\n€654\nSelect\n"

    kept = KayakSource._validate(rows, body)
    assert [r["airline"] for r in kept] == ["Iberia"]


async def test_validate_keeps_the_multiple_airlines_label_the_page_prints():
    """Checked before assuming: "Multiple airlines" occurs 8 times in the real
    captured body -- it is Kayak's own row label for multi-carrier
    self-transfer itineraries, not a model invention. Honest data, and it must
    not be filtered out."""
    from backend.sources.kayak import KayakSource

    rows = [{"airline": "Multiple airlines", "flight_number": "", "price": 654.0,
             "departure_time": "2026-08-21T03:50:00",
             "arrival_time": "2026-08-22T22:20:00"}]
    body = "Multiple airlines\n3:50 am – 10:20 pm+1\n€654\nSelect\n"

    assert len(KayakSource._validate(rows, body)) == 1


async def test_validate_keeps_the_first_carrier_of_a_comma_joined_label():
    from backend.sources.kayak import KayakSource

    rows = [{"airline": "Arajet", "flight_number": "", "price": 654.0,
             "departure_time": "2026-08-21T03:50:00",
             "arrival_time": "2026-08-22T22:20:00"}]
    body = "Arajet, Iberia\n3:50 am – 10:20 pm+1\n€654\nSelect\n"

    assert len(KayakSource._validate(rows, body)) == 1


async def test_validate_keeps_airline_differing_only_in_case_from_the_page():
    """make_flight_key casefolds the airline, so a pure case difference is not
    a fabrication and must not be treated as one."""
    from backend.sources.kayak import KayakSource

    rows = [{"airline": "TAP AIR PORTUGAL", "flight_number": "", "price": 654.0,
             "departure_time": "2026-08-21T03:50:00",
             "arrival_time": "2026-08-22T22:20:00"}]
    body = "TAP Air Portugal\n3:50 am – 10:20 pm+1\n€654\nSelect\n"

    assert len(KayakSource._validate(rows, body)) == 1
