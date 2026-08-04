from backend.sources.base import SearchSource
from backend.sources.fallback import FallbackSource


def get_sources() -> list[SearchSource]:
    # KayakSource is deliberately not listed here: it is per-tracker opt-in
    # (trackers.kayak_enabled), not run unconditionally on every cycle, so
    # backend/scheduler.py::search_and_store constructs it directly instead.
    return [FallbackSource()]
