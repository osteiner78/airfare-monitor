from backend.sources.base import FlightResult
from backend.sources.fast_flights import FastFlightsSource
from backend.sources.google_flights import GoogleFlightsSource


class FallbackSource:
    """Tries fli (primary) first; only calls fast_flights if fli comes back empty."""

    def __init__(self) -> None:
        self.primary = GoogleFlightsSource()
        self.secondary = FastFlightsSource()
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

        results = await self.primary.search(origin, dest, depart_date, return_date, currency, top_n)
        if results:
            return results

        primary_error = self.primary.last_error
        primary_level = self.primary.last_error_level

        results = await self.secondary.search(origin, dest, depart_date, return_date, currency, top_n)
        if results:
            # Falling back is a silent quality drop, not a success: fast_flights
            # returns far fewer and coarser rows, so the dashboard's headline
            # price can jump hundreds of euros with nothing in system_logs to
            # explain it (observed 2026-08-11: fli 113 rows cheapest EUR784 ->
            # fast_flights 6 rows cheapest EUR957, no log line at all).
            # WARNING, not ERROR: the cycle did produce prices.
            self.last_error = (
                f"fli returned no rows ({primary_error or 'no error reported'}); "
                f"served {len(results)} row(s) from fast_flights instead"
            )
            self.last_error_level = "WARNING"
            return results

        secondary_error = self.secondary.last_error
        secondary_level = self.secondary.last_error_level

        if primary_error or secondary_error:
            self.last_error = f"fli: {primary_error or 'no error'}; fast_flights: {secondary_error or 'no error'}"
            levels = [lvl for err, lvl in ((primary_error, primary_level), (secondary_error, secondary_level)) if err]
            self.last_error_level = "ERROR" if "ERROR" in levels else "WARNING"

        return results
