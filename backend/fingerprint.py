from backend.sources.base import FlightResult


def _normalize_airline(airline: str) -> str:
    # Kayak prints "GOL" where Google prints "Gol" (verified against the
    # captured bodies and the live flight_prices table), so a case-sensitive
    # airline segment forks one physical flight into two identities across
    # sources -- the exact failure this key format exists to prevent.
    # ASCII-equivalent to the backfill's LOWER(TRIM(...)) for every airline
    # string in the production table (checked before plan 019's migration).
    return " ".join((airline or "").split()).casefold()


def make_flight_key(result: FlightResult) -> str:
    # flight_number is deliberately absent (plan 019): Kayak's collapsed list
    # view prints none, so including it gave one flight several identities.
    return (
        f"{_normalize_airline(result.airline)}"
        f"|{result.departure_time}|{result.arrival_time}"
    )
