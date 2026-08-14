"""The authoritative identity layer: what makes two rows the same flight.

Every normalisation that feeds a `flight_key` lives here, and every other
layer defers to it rather than reimplementing it. That rule exists because
the alternative was tried: identity logic spread across five functions in
three layers produced two production defects in one week -- rows deduped
before the normalisation that makes them identical (`130b205`), and one
carrier forking into two identities across sources (`d23d5a8`). Both were
fixed as instances; this module is the fix as a class.

If a new source needs its raw values massaged before they can be compared,
the massaging belongs in this file, not in the source -- a source-local
normalisation is invisible to the identity layer and silently stops applying
the moment another source appears.
"""

from datetime import datetime

from backend.airlines import AIRLINE_NAME_TO_CODE
from backend.sources.base import FlightResult


def normalize_airline(airline: str) -> str:
    """The one airline identity, shared by the stored key and the UI facets.

    Three collapses, each earned by a real fork:
    - the carrier LIST -- Kayak names a connecting itinerary by every
      operator ("Azul, easyJet") where the Google sources emit only the first
      (`r.airlines[0]`), so the tail would fork such flights forever.
    - CASE -- Kayak prints "GOL"/"TAP AIR PORTUGAL" where Google prints
      "Gol"/"Tap Air Portugal".
    - shortened-vs-full NAMES -- Google's bare "LATAM"/"ITA" against Kayak's
      "LATAM Airlines"/"ITA Airways". Casefolding cannot bridge these; they
      forked in production until plan 024 phase 4. Mapped names collapse to
      their IATA code, unmapped names keep the casefolded text.

    The SQL `LOWER(TRIM(...))` shortcut is doubly wrong for this -- it cannot
    consult the map and it does not collapse internal whitespace -- so the
    backfill script must keep calling this function rather than reimplementing
    it.
    """
    first_carrier = str(airline or "").split(",")[0]
    normalized = " ".join(first_carrier.split())
    return (AIRLINE_NAME_TO_CODE.get(normalized.upper()) or normalized).casefold()


def canonical_timestamp(value) -> str:
    """One ISO spelling per instant, so two sources' keys can line up.

    Kayak's extraction model alternates between "2026-10-04T00:30" and
    "...T00:30:00" for the same flight across runs (observed live
    2026-08-05), and both times are two thirds of the key. `isoformat()` is
    also exactly what the Google sources already emit, which is what makes
    the two line up.

    Unparseable values pass through unchanged on purpose: the row is still
    worth storing, and `_validate` -- not this function -- is the guard that
    decides whether a value is trustworthy.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def make_flight_key(result: FlightResult) -> str:
    # flight_number is deliberately absent (plan 019): Kayak's collapsed list
    # view prints none, so including it gave one flight several identities.
    #
    # The timestamps are canonicalised HERE rather than trusted from the
    # caller. A source that forgets to normalise cannot produce a wrong key,
    # which is the difference between "every source must remember" and "the
    # identity layer does it".
    return (
        f"{normalize_airline(result.airline)}"
        f"|{canonical_timestamp(result.departure_time)}"
        f"|{canonical_timestamp(result.arrival_time)}"
    )
