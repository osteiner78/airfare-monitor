"""Prices printed on the page that do not belong to the tracked itinerary.

Grounding (`_validate`) only asks whether a value appears in the rendered text,
never whether it belongs to the row it was attached to -- so any real price
printed for something else is invisible to it. Paid placements were the first
instance (plan 020). Two more are covered here:

1. NEARBY-AIRPORT PROMOS -- observed live 2026-08-11 on GRU-ZRH:

       Save money
       Depart from nearby VCP and save EUR78 - 51 mi from GRU
       from
       EUR706
       Show all

   `_results_section` slices from the top of the results, so this block and
   its EUR706 landed in the extraction input. That fare departs VCP, not GRU.

2. PLACEMENT VARIANTS `Sponsored` / `| Ad` -- named in plan 019's write-up but
   NEVER observed: 0 occurrences across every captured body. Handled
   precautionarily and pinned here, including the over-stripping they could
   cause if matched loosely, which would be worse than the bug.
"""

import pytest

from backend.sources.kayak import (
    _NEARBY_AIRPORT_MAX_BLOCK_LINES,
    _PLACEMENT_MAX_BLOCK_LINES,
    _strip_nearby_airport_promos,
    _strip_placements,
)

# Verbatim shape of the real block, from data/kayak-samples/20260811T021328.
_REAL_NEARBY_PROMO = """Save money
Depart from nearby VCP and save €78 • 51 mi from GRU
from
€706
Show all
Go to next result
8:45 pm – 5:15 pm+1
TAP AIR PORTUGAL
1 stop
€784
Select"""


# --- 1. nearby-airport promos ---

def test_nearby_airport_price_is_removed():
    out = _strip_nearby_airport_promos(_REAL_NEARBY_PROMO)
    assert "€706" not in out, "a fare from a different airport reached the extractor"
    assert "Depart from nearby" not in out


def test_the_real_itinerary_survives_the_strip():
    """The whole risk of stripping: never destroy good data."""
    out = _strip_nearby_airport_promos(_REAL_NEARBY_PROMO)
    assert "€784" in out
    assert "TAP AIR PORTUGAL" in out
    assert "8:45 pm – 5:15 pm+1" in out
    assert "Select" in out


def test_a_promo_without_its_terminator_drops_only_its_own_line():
    """No 'Show all' to anchor on: strip the promo line, never guess how far
    the block runs. Guessing would silently eat the results below it."""
    body = "Depart from nearby VCP and save €78\n€706\n8:45 pm – 5:15 pm+1\n€784\nSelect"
    out = _strip_nearby_airport_promos(body)
    assert "Depart from nearby" not in out
    assert "€784" in out and "Select" in out


def test_a_far_away_show_all_does_not_swallow_the_results():
    body = (
        ["Depart from nearby VCP and save €78", "€706"]
        + [f"€{900 + i}" for i in range(_NEARBY_AIRPORT_MAX_BLOCK_LINES + 5)]
        + ["Show all"]
    )
    out = _strip_nearby_airport_promos("\n".join(body))
    assert "€900" in out, "results beyond the block bound were stripped"


def test_body_without_a_promo_is_untouched():
    body = "8:45 pm – 5:15 pm+1\nTAP AIR PORTUGAL\n€784\nSelect"
    assert _strip_nearby_airport_promos(body) == body


# --- 2. the previously untested placement variants ---

@pytest.mark.parametrize("marker", ["Sponsored", "| Ad", "Ad |"])
def test_alternate_placement_markers_strip_their_block(marker):
    body = f"{marker}\nCheap flights from Expedia\n€805\nView Deal\n8:45 pm – 5:15 pm+1\n€784\nSelect"
    out = _strip_placements(body)
    assert "€805" not in out, f"{marker!r} placement price survived"
    assert "€784" in out and "Select" in out


@pytest.mark.parametrize("marker", ["Sponsored", "| Ad"])
def test_alternate_markers_only_match_a_whole_line(marker):
    """The dangerous direction. These words in ordinary copy must NOT start a
    block -- matching mid-sentence would strip every price up to the next
    'View Deal', which is real data loss dressed up as a fix."""
    body = (
        f"Airlines often run a Sponsored fare or an Ad campaign, see {marker} details\n"
        "8:45 pm – 5:15 pm+1\n€784\nView Deal\nSelect"
    )
    out = _strip_placements(body)
    assert "€784" in out, "a real fare was stripped by a substring match"


def test_placement_block_is_bounded():
    """A start marker with no terminator must not consume the rest of the page."""
    body = (
        ["Sponsored"]
        + [f"€{900 + i}" for i in range(_PLACEMENT_MAX_BLOCK_LINES + 5)]
        + ["View Deal"]
    )
    out = _strip_placements("\n".join(body))
    assert "€900" in out, "an unterminated placement stripped the whole page"


def test_the_original_disclosure_form_still_works():
    """Regression guard on plan 020's actual fix while adding variants."""
    body = (
        "Book your flight to unlock more savings This is a paid placement from "
        "Expedia. €805 View Deal\n€805\n€1,406\nExpedia\nAd\n€805\nView Deal\n"
        "8:45 pm – 5:15 pm+1\n€784\nSelect"
    )
    out = _strip_placements(body)
    assert "€805" not in out and "€1,406" not in out
    assert "€784" in out and "Select" in out
