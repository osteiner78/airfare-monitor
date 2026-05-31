from backend.sources.base import FlightResult


def make_flight_key(result: FlightResult) -> str:
    return f"{result.source}|{result.airline}|{result.flight_number}|{result.departure_time}"
