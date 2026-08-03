from backend.sources.base import SearchSource
from backend.sources.fallback import FallbackSource


def get_sources() -> list[SearchSource]:
    return [FallbackSource()]
