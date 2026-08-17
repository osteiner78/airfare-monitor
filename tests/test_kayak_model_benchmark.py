"""Tests for scripts/kayak_model_benchmark.py (plan 027 #4).

The benchmark had drifted from production on two axes: an unparseable
timestamp scored as ungrounded (production keeps it) and a 24-hour-page body
had no fallback (production falls back to the 24h form on a pt-BR/de-CH
force-redirect). Both differences trace to the benchmark keeping its own copy
of `_time_grounded` instead of importing production's. This file pins that
the copy is gone -- the benchmark now uses the same object production does,
so the two can never again silently diverge.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.kayak_model_benchmark as bench
from backend.sources.kayak import KayakSource


def test_benchmark_grounding_function_is_productions():
    """Not just equal behaviour -- the same object, so a future edit to
    KayakSource._time_grounded can't be forgotten on the benchmark side."""
    assert bench._time_grounded is KayakSource._time_grounded


def test_benchmark_grounding_keeps_an_unparseable_time():
    """Production keeps a row whose timestamp can't be parsed rather than
    scoring it ungrounded -- the drifted local copy returned False here,
    which the benchmark's own docstring never intended to test."""
    assert bench._keys_time_grounded(["royal air maroc|tomorrow morning|"], "irrelevant") is True


def test_benchmark_grounding_falls_back_to_24_hour_form():
    """A pt-BR/de-CH force-redirect prints no am/pm anywhere on the page --
    production falls back to the 24h form rather than dropping every row of
    a perfectly good page, and the drifted local copy had no such fallback."""
    body = "00:30 – 17:40\nRoyal Air Maroc\n1 stop\nGRU\n-\nLIS\n"
    key = "royal air maroc|2026-10-04T00:30:00|2026-10-04T17:40:00"

    assert bench._keys_time_grounded([key], body) is True
