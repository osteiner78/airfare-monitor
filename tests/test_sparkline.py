"""Plan 012 Phase 1 — fail-first tests for the redesigned `_sparkline`.

The new contract:
  - floors the visual y-band to MIN_SPAN_FRAC (0.06) of the mean price and
    CENTERS small ranges, so trivial price moves render near-flat;
  - marks the all-time low (`low_x`/`low_y`/`low_price`, most-recent min) and the
    current point (`last_x`/`last_y`/`last_price`); the series-start label is gone
    (`first_x`/`first_price` removed);
  - plot band is [pad, h-pad] using the PASSED h; returned `h` = passed_h + label band.

These pin behavior that does not exist yet — they fail against the current
implementation and pass once Phase 1 lands.
"""

from backend.pages import _sparkline


# Geometry constants mirroring the params we pass below (NOT the function defaults,
# so the tests stay deterministic regardless of any default change).
W, H, PAD = 132, 34, 4
PLOT_TOP = PAD                 # y of the highest price
PLOT_BOTTOM = H - PAD          # y of the lowest price
PLOT_CENTER = PAD + (H - 2 * PAD) / 2   # 17.0


def _spark(prices):
    return _sparkline(prices, w=W, h=H, pad=PAD)


def _xy_pairs(points: str):
    pairs = []
    for tok in points.split():
        x, y = tok.split(",")
        pairs.append((float(x), float(y)))
    return pairs


def _x_at(index: int, n: int) -> float:
    return round(PAD + (W - 2 * PAD) * index / (n - 1), 1)


# ── return-None guards ──────────────────────────────────────────────────────

def test_returns_none_for_empty():
    assert _spark([]) is None


def test_returns_none_for_single_point():
    assert _spark([100]) is None


# ── new contract keys ───────────────────────────────────────────────────────

def test_start_label_keys_removed_and_low_keys_present():
    s = _spark([500, 480, 495])
    assert "first_x" not in s
    assert "first_price" not in s
    for key in ("low_x", "low_y", "low_price", "last_x", "last_y", "last_price"):
        assert key in s


# ── scaling floor: small moves look flat, big moves use the height ──────────

def test_small_relative_change_stays_near_flat():
    # €1 swing on a ~€450 fare must NOT span the chart.
    s = _spark([450, 451])
    assert abs(s["low_y"] - s["last_y"]) < 4.0          # near-flat (px)
    # both endpoints sit in the central band, not pinned top/bottom
    assert 12.0 < s["low_y"] < 22.0
    assert 12.0 < s["last_y"] < 22.0


def test_large_relative_change_uses_full_height():
    # A genuine 2x move should reach the band extremes.
    s = _spark([300, 600])
    assert s["low_price"] == 300
    assert s["low_y"] >= PLOT_BOTTOM - 2          # cheapest near the floor
    assert s["last_y"] <= PLOT_TOP + 2            # priciest (current) near the top


def test_flat_series_is_midline():
    s = _spark([400, 400, 400])
    assert s["trend"] == "flat"
    for _, y in _xy_pairs(s["points"]):
        assert abs(y - PLOT_CENTER) < 0.01
    assert abs(s["low_y"] - PLOT_CENTER) < 0.01
    assert abs(s["last_y"] - PLOT_CENTER) < 0.01


# ── all-time-low marker ─────────────────────────────────────────────────────

def test_low_marker_is_series_min():
    s = _spark([500, 480, 495])
    assert s["low_price"] == 480


def test_low_marker_picks_most_recent_min():
    # 480 occurs at index 0 and index 2 → marker must be the LAST occurrence.
    s = _spark([480, 500, 480])
    assert s["low_x"] == _x_at(2, 3)


def test_last_point_is_current_price():
    s = _spark([500, 480, 495])
    assert s["last_price"] == 495
    assert s["last_x"] == _x_at(2, 3)


# ── trend classification (preserve current semantics) ───────────────────────

def test_trend_down():
    assert _spark([100, 90])["trend"] == "down"


def test_trend_up():
    assert _spark([90, 100])["trend"] == "up"


def test_trend_flat():
    assert _spark([100, 100])["trend"] == "flat"


# ── failure-mode / edge ─────────────────────────────────────────────────────

def test_filters_none_values():
    s = _spark([100, None, 120])
    assert s is not None
    assert s["low_price"] == 100
    assert s["last_price"] == 120


def test_two_identical_prices_no_div_by_zero():
    s = _spark([200, 200])
    assert s["trend"] == "flat"
    assert abs(s["low_y"] - PLOT_CENTER) < 0.01
    assert abs(s["last_y"] - PLOT_CENTER) < 0.01


def test_step_series_coords_within_bounds():
    s = _spark([450, 450, 451, 450, 451, 451])
    total_h = s["h"]
    for x, y in _xy_pairs(s["points"]):
        assert 0 <= x <= W
        assert 0 <= y <= total_h
    assert 0 <= s["low_x"] <= W
    assert 0 <= s["last_x"] <= W


def test_near_zero_prices_no_div_by_zero():
    s = _spark([1, 2])
    assert s is not None
    assert s["low_price"] == 1
    # coordinates are finite
    assert s["low_y"] == s["low_y"]   # not NaN
    assert s["last_y"] == s["last_y"]
