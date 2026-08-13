from backend.airlines import AIRLINE_NAME_TO_CODE
from backend.sources.base import FlightResult


def _normalize_airline(airline: str) -> str:
    # Kayak prints "GOL" where Google prints "Gol" (verified against the
    # captured bodies and the live flight_prices table), so a case-sensitive
    # airline segment forks one physical flight into two identities across
    # sources -- the exact failure this key format exists to prevent.
    # Casefolding alone only bridges CASE differences: Google/fli prints
    # "LATAM"/"ITA" where Kayak prints "LATAM Airlines"/"ITA Airways", and
    # those forked in production (plan 024 phase 4). Mapped names collapse to
    # their IATA code; unmapped names keep the casefolded form. The SQL
    # LOWER(TRIM(...)) shortcut is now doubly wrong -- it cannot consult the
    # map -- so the backfill must keep calling this function.
    normalized = " ".join((airline or "").split())
    return (AIRLINE_NAME_TO_CODE.get(normalized.upper()) or normalized).casefold()


def make_flight_key(result: FlightResult) -> str:
    # flight_number is deliberately absent (plan 019): Kayak's collapsed list
    # view prints none, so including it gave one flight several identities.
    return (
        f"{_normalize_airline(result.airline)}"
        f"|{result.departure_time}|{result.arrival_time}"
    )
