from backend.sources.base import SearchSource
from backend.sources.google_flights import GoogleFlightsSource


def get_sources() -> list[SearchSource]:
    return [GoogleFlightsSource()]
