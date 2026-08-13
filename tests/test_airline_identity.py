"""Plan 024 phase 4 -- airline identity across name variants.

The 022/023 reviews both found that one physical flight forks into two
flight_keys when two sources print the same carrier under different NAMES
(not merely different casing, which _normalize_airline already bridged):
Google/fli prints "LATAM"/"ITA" where Kayak prints "LATAM Airlines"/"ITA
Airways". Confirmed live -- 33,630 google + 234 fast_flights rows under
"LATAM" against 135 kayak rows under "LATAM Airlines", with forked pairs in
the SAME snapshot (7242, 7238, 7124, 7122, 7118, 7117, 7116).

The identity now consults the shared name -> IATA map, so mapped variants
collapse to one key and unmapped names keep the pre-existing behaviour.
"""

import pytest

from backend.airlines import AIRLINE_NAME_TO_CODE
from backend.fingerprint import make_flight_key
from backend.sources.base import FlightResult


def make_result(**overrides):
    defaults = dict(
        source="google_flights",
        price=199.0,
        currency="EUR",
        duration_min=90,
        stops=0,
        airline="LX",
        flight_number="LX1234",
        departure_time="2026-06-15T07:30:00+02:00",
        arrival_time="2026-06-15T09:00:00+02:00",
        legs_json="[]",
        booking_url="https://example.com",
    )
    defaults.update(overrides)
    return FlightResult(**defaults)


# --- the two forks observed in production ---

async def test_latam_and_latam_airlines_share_one_key():
    google = make_flight_key(make_result(source="google_flights", airline="LATAM"))
    kayak = make_flight_key(make_result(source="kayak", airline="LATAM Airlines"))
    assert google == kayak


async def test_ita_and_ita_airways_share_one_key():
    google = make_flight_key(make_result(source="google_flights", airline="ITA"))
    kayak = make_flight_key(make_result(source="kayak", airline="ITA Airways"))
    assert google == kayak


# --- the broad form: every pair sharing a map entry ---

def _name_variant_pairs():
    by_code: dict[str, list[str]] = {}
    for name, code in AIRLINE_NAME_TO_CODE.items():
        by_code.setdefault(code, []).append(name)
    pairs = []
    for code, names in by_code.items():
        for other in names[1:]:
            pairs.append((code, names[0], other))
    return pairs


@pytest.mark.parametrize("code,name_a,name_b", _name_variant_pairs())
async def test_every_pair_sharing_a_map_entry_shares_one_key(code, name_a, name_b):
    assert make_flight_key(make_result(airline=name_a)) == make_flight_key(
        make_result(airline=name_b)
    )


async def test_the_map_actually_carries_variant_pairs():
    """Guards the parametrised test above against silently covering nothing if
    the map is ever reduced to one name per code."""
    assert len(_name_variant_pairs()) >= 5


# --- mapped names collapse to the code, not to a canonical name ---

async def test_a_mapped_name_normalises_to_its_iata_code():
    key = make_flight_key(make_result(airline="LATAM Airlines"))
    assert key.split("|")[0] == "la"


async def test_case_and_whitespace_still_reach_the_map():
    keys = {
        make_flight_key(make_result(airline=name))
        for name in ("latam airlines", "LATAM  Airlines", "  LATAM Airlines  ")
    }
    assert len(keys) == 1


# --- unmapped names keep the pre-plan-024 behaviour ---

async def test_an_unmapped_name_keeps_the_casefolded_form():
    key = make_flight_key(make_result(airline="Multiple airlines"))
    assert key.split("|")[0] == "multiple airlines"


async def test_an_unmapped_name_still_collapses_whitespace_and_case():
    key_a = make_flight_key(make_result(airline="  Some   Regional Air  "))
    key_b = make_flight_key(make_result(airline="some regional air"))
    assert key_a == key_b


async def test_distinct_carriers_still_get_distinct_keys():
    keys = {
        make_flight_key(make_result(airline=name))
        for name in ("LATAM Airlines", "ITA Airways", "Iberia", "Multiple airlines")
    }
    assert len(keys) == 4


# --- the map lives in a leaf module both consumers can import ---

async def test_pages_and_fingerprint_share_one_map_object():
    """pages.py cannot be imported by fingerprint.py -- that import direction is
    part of why the two normalisations diverged in the first place."""
    import backend.pages as pages

    assert pages._AIRLINE_NAME_TO_CODE is AIRLINE_NAME_TO_CODE
