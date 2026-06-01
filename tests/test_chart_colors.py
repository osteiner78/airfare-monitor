"""Unit tests for the server-side flight_key -> color assignment (plan 009).

These pin the single source of truth used by BOTH the chart datasets and the
results-table row accents. The function is imported inside each test so that,
before implementation, each test fails on a missing-symbol error rather than
breaking collection for the whole file.
"""


# --- NEW-BEHAVIOR ---

def test_single_key_gets_first_palette_color():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    assert _assign_chart_colors(["k1"]) == {"k1": CHART_COLORS[0]}


def test_distinct_colors_for_keys_within_palette_size():
    from backend.pages import _assign_chart_colors
    result = _assign_chart_colors(["a", "b", "c"])
    assert len(set(result.values())) == 3


def test_assigns_colors_in_positional_order():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    result = _assign_chart_colors(["a", "b"])
    assert result["a"] == CHART_COLORS[0] and result["b"] == CHART_COLORS[1]


def test_handles_unicode_and_pipe_delimited_keys():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    keys = ["test|VY|6201|2026-01-01T00:00:00", "✈|x|1|t"]
    result = _assign_chart_colors(keys)
    assert result["✈|x|1|t"] == CHART_COLORS[1]


# --- FAILURE-MODE / edge cases ---

def test_returns_empty_dict_for_empty_key_list():
    from backend.pages import _assign_chart_colors
    assert _assign_chart_colors([]) == {}


def test_palette_cycles_when_more_keys_than_colors():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    keys = [f"k{i}" for i in range(12)]
    result = _assign_chart_colors(keys)
    assert all(color in CHART_COLORS for color in result.values())


def test_eleventh_key_reuses_first_color():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    keys = [f"k{i}" for i in range(11)]
    result = _assign_chart_colors(keys)
    assert result["k10"] == CHART_COLORS[0]


def test_duplicate_keys_collapse_to_single_entry():
    from backend.pages import _assign_chart_colors, CHART_COLORS
    result = _assign_chart_colors(["a", "a"])
    assert result == {"a": CHART_COLORS[1]}
