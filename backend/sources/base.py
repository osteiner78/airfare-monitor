from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class FlightResult:
    source: str
    price: float
    currency: str
    duration_min: int | None
    stops: int
    airline: str
    flight_number: str
    departure_time: str
    arrival_time: str
    legs_json: str
    booking_url: str


@runtime_checkable
class SearchSource(Protocol):
    async def search(
        self,
        origin: str,
        dest: str,
        depart_date: str,
        return_date: str | None,
        currency: str,
        top_n: int,
    ) -> list[FlightResult]: ...
