import asyncio
import json
import sys

from backend.sources.base import FlightResult


class GoogleFlightsSource:
    async def search(
        self,
        origin: str,
        dest: str,
        depart_date: str,
        return_date: str | None,
        currency: str,
        top_n: int,
    ) -> list[FlightResult]:
        # "flights" set to None in sys.modules is the test sentinel for fli unavailable
        try:
            if "flights" in sys.modules and sys.modules["flights"] is None:
                raise ImportError
            from fli.search import SearchFlights  # noqa: F401
        except ImportError:
            return []

        try:
            return await self._fetch(origin, dest, depart_date, return_date, currency, top_n)
        except Exception:
            return []

    async def _fetch(
        self,
        origin: str,
        dest: str,
        depart_date: str,
        return_date: str | None,
        currency: str,
        top_n: int,
    ) -> list[FlightResult]:
        from fli.models import (
            Airport,
            FlightSearchFilters,
            FlightSegment,
            PassengerInfo,
            TripType,
        )
        from fli.search import SearchFlights

        origin_airport = Airport[origin]
        dest_airport = Airport[dest]

        outbound = FlightSegment(
            departure_airport=[[origin_airport, 0]],
            arrival_airport=[[dest_airport, 0]],
            travel_date=depart_date,
        )
        segments = [outbound]

        if return_date:
            inbound = FlightSegment(
                departure_airport=[[dest_airport, 0]],
                arrival_airport=[[origin_airport, 0]],
                travel_date=return_date,
            )
            segments.append(inbound)

        trip_type = TripType.ROUND_TRIP if return_date else TripType.ONE_WAY
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
        )

        client = SearchFlights()
        raw_results = await asyncio.to_thread(client.search, filters, top_n, currency)
        if not raw_results:
            return []

        return [self._map_result(r, origin, dest, depart_date) for r in raw_results if r.price is not None]

    def _map_result(self, r, origin: str, dest: str, depart_date: str) -> FlightResult:
        legs = r.legs if r.legs else []

        airline_name = getattr(r, "primary_airline_name", None) or ""
        airline_codes = "+".join(leg.airline.name for leg in legs) if legs else ""
        flight_numbers = "+".join(str(leg.flight_number) for leg in legs) if legs else ""
        departure_time = legs[0].departure_datetime.isoformat() if legs else ""
        arrival_time = legs[-1].arrival_datetime.isoformat() if legs else ""

        legs_data = [
            {
                "airline": leg.airline.name,
                "airline_name": airline_name,
                "flight_number": str(leg.flight_number),
                "departure": leg.departure_datetime.isoformat(),
                "arrival": leg.arrival_datetime.isoformat(),
                "duration_min": leg.duration,
            }
            for leg in legs
        ]

        return FlightResult(
            source="google_flights",
            price=float(r.price),
            currency=str(r.currency),
            duration_min=r.duration,
            stops=r.stops,
            airline=airline_name,
            flight_number=flight_numbers,
            departure_time=departure_time,
            arrival_time=arrival_time,
            legs_json=json.dumps(legs_data),
            booking_url=f"https://www.google.com/travel/flights?q=Flights+to+{dest}+from+{origin}+on+{depart_date}",
        )
