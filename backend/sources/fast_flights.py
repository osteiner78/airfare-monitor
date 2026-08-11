import asyncio
import json

from backend.sources.base import FlightResult


class FastFlightsSource:
    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_error_level: str = "ERROR"

    async def search(
        self,
        origin: str,
        dest: str,
        depart_date: str,
        return_date: str | None,
        currency: str,
        top_n: int,
    ) -> list[FlightResult]:
        self.last_error = None

        try:
            import fast_flights  # noqa: F401
        except ImportError:
            return []

        try:
            return await self._fetch(origin, dest, depart_date, return_date, currency, top_n)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.last_error_level = "ERROR"
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
        import fast_flights
        from fast_flights.exceptions import FlightsNotFound

        if return_date:
            # A single fetch only returns the outbound-leg selection screen
            # (each result carries one SingleFlight, not the full round-trip
            # itinerary) -- confirmed by testing, not documented. Storing that
            # as if it were a complete round-trip result would silently
            # corrupt price/leg data, so fail loudly instead. No tracker in
            # this DB currently uses return_date; fli (primary) still handles
            # round-trip correctly.
            raise NotImplementedError("fast_flights round-trip fetch is not supported yet")

        query = fast_flights.create_query(
            flights=[fast_flights.FlightQuery(date=depart_date, from_airport=origin, to_airport=dest)],
            trip="one-way",
            currency=currency or "",
        )

        html = await asyncio.to_thread(fast_flights.fetch_flights_html, query)

        try:
            results = fast_flights.parser.parse(html)
        except FlightsNotFound:
            results = None

        if not results:
            self.last_error = "fast_flights returned no results (route may genuinely have none)"
            self.last_error_level = "WARNING"
            return []

        flight_numbers = self._extract_flight_numbers(html)

        mapped = [
            self._map_result(r, flight_numbers[i] if i < len(flight_numbers) else [], currency, query)
            for i, r in enumerate(results)
        ]

        # A row whose timestamp _to_iso could not build is unidentifiable:
        # make_flight_key is airline|departure|arrival, so an empty component
        # yields "tap air portugal||2026-08-21T22:30:00" -- which every flight
        # by that airline arriving then collapses into, merging genuinely
        # different itineraries under one identity and one chart line. Keeping
        # the row was only safe while the key still carried flight_number;
        # plan 019 removed it, and this was missed at the time (96 such rows
        # reached production before it was noticed on 2026-08-11).
        usable = [r for r in mapped if r.departure_time and r.arrival_time]
        dropped = len(mapped) - len(usable)
        if dropped:
            self.last_error = (
                f"dropped {dropped} of {len(mapped)} rows with an unusable "
                "departure/arrival time (Google returned a null date component)"
            )
            self.last_error_level = "WARNING"
        return usable

    @staticmethod
    def _extract_flight_numbers(html: str) -> list[list[str]]:
        """Recover real flight numbers from the raw ds:1 payload.

        fast_flights' own parser doesn't expose index 22 of each leg's raw
        array, which is [airline_code, flight_number, None, airline_name] --
        confirmed by inspecting the payload directly (see
        .agent/plans/016-fast-flights-fallback.md). Kept isolated so a shape
        change here can't take down price/route parsing in _fetch.
        """
        from selectolax.lexbor import LexborHTMLParser

        parser = LexborHTMLParser(html)
        script = parser.css_first(r"script.ds\:1")
        if script is None:
            return []

        js = script.text()
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data)
        if not payload[3][0]:
            return []

        itineraries: list[list[str]] = []
        for itinerary in payload[3][0]:
            legs = itinerary[0][2]
            numbers = []
            for leg in legs:
                try:
                    code, number = leg[22][0], leg[22][1]
                    numbers.append(f"{code} {number}" if code and number else "")
                except (IndexError, TypeError):
                    numbers.append("")
            itineraries.append(numbers)
        return itineraries

    def _map_result(self, r, leg_numbers: list[str], currency: str, query) -> FlightResult:
        legs = r.flights
        airline = r.airlines[0] if r.airlines else ""
        flight_number = "+".join(n for n in leg_numbers if n)
        duration_min = sum(leg.duration for leg in legs) if legs else None

        departure_time = self._to_iso(legs[0].departure) if legs else ""
        arrival_time = self._to_iso(legs[-1].arrival) if legs else ""

        legs_data = [
            {
                "airline": airline,
                "flight_number": leg_numbers[i] if i < len(leg_numbers) else "",
                "departure": self._to_iso(leg.departure),
                "arrival": self._to_iso(leg.arrival),
                "duration_min": leg.duration,
                "plane_type": leg.plane_type,
            }
            for i, leg in enumerate(legs)
        ]

        return FlightResult(
            source="fast_flights",
            price=float(r.price),
            currency=currency,
            duration_min=duration_min,
            stops=max(len(legs) - 1, 0),
            airline=airline,
            flight_number=flight_number,
            departure_time=departure_time,
            arrival_time=arrival_time,
            legs_json=json.dumps(legs_data),
            booking_url=query.url(),
        )

    @staticmethod
    def _to_iso(dt) -> str:
        y, m, d = dt.date
        # Google omits the minute when it's ":00" (e.g. time=[14] not [14, 0])
        h = dt.time[0] if dt.time else None
        mi = dt.time[1] if len(dt.time) > 1 else 0

        # Google intermittently returns a None component here, which used to
        # raise out of _map_result and kill the WHOLE fetch (the comprehension
        # in _fetch), not just the offending leg -- 61 zero-result ERRORs in
        # production over ~27h. Minute is safe to default (Google already omits
        # it when :00); hour or date is not -- departure_time feeds flight_key,
        # so a fabricated midnight would forge a flight identity. Degrade to ""
        # instead, and let _fetch DROP the row: since plan 019 the key no
        # longer carries flight_number, so "" no longer degrades to a usable
        # identity the way this comment once described -- it collides.
        if mi is None:
            mi = 0
        if any(part is None for part in (y, m, d, h)):
            return ""

        return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:00"
