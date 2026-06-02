# Plan 013 Phase 1 — `_sparkline` rail geometry + de-collision

## What was built

**Task 1.1**: Added `_MIN_GAP_FRAC = 0.40`, `_RAIL_MARGIN = 0.14`, and `_rail_positions(current_frac, low_frac)` to `backend/pages.py`. The helper pushes the two y-fracs apart if they're less than 0.40 apart, then clamps both into `[0.14, 0.86]`, preserving the gap.

**Task 1.2**: Rewrote `_sparkline`'s return dict: removed `label_y` and the `label_h` band (h is now the passed height, default 34); added `last_y_frac`, `low_y_frac`, `at_all_time_low`, `current_rail`, `alltime_rail`.

## Verification output

```
.venv/bin/python -m pytest tests/test_sparkline.py -v
============================= test session starts ==============================
...
tests/test_sparkline.py::test_returns_none_for_empty PASSED
tests/test_sparkline.py::test_returns_none_for_single_point PASSED
tests/test_sparkline.py::test_start_label_keys_removed_and_low_keys_present PASSED
tests/test_sparkline.py::test_small_relative_change_stays_near_flat PASSED
tests/test_sparkline.py::test_large_relative_change_uses_full_height PASSED
tests/test_sparkline.py::test_flat_series_is_midline PASSED
tests/test_sparkline.py::test_low_marker_is_series_min PASSED
tests/test_sparkline.py::test_low_marker_picks_most_recent_min PASSED
tests/test_sparkline.py::test_last_point_is_current_price PASSED
tests/test_sparkline.py::test_trend_down PASSED
tests/test_sparkline.py::test_trend_up PASSED
tests/test_sparkline.py::test_trend_flat PASSED
tests/test_sparkline.py::test_filters_none_values PASSED
tests/test_sparkline.py::test_two_identical_prices_no_div_by_zero PASSED
tests/test_sparkline.py::test_step_series_coords_within_bounds PASSED
tests/test_sparkline.py::test_near_zero_prices_no_div_by_zero PASSED
tests/test_sparkline.py::test_returns_rail_fractions PASSED
tests/test_sparkline.py::test_label_band_removed PASSED
tests/test_sparkline.py::test_current_rail_never_below_alltime PASSED
tests/test_sparkline.py::test_rail_gap_enforced_when_dots_close PASSED
tests/test_sparkline.py::test_at_all_time_low_true_when_current_is_min PASSED
tests/test_sparkline.py::test_at_all_time_low_false_when_current_above_min PASSED
tests/test_sparkline.py::test_at_all_time_low_true_when_min_repeats_at_end PASSED
tests/test_sparkline.py::test_rail_positions_far_apart_within_margins_unchanged PASSED
tests/test_sparkline.py::test_rail_positions_close_pushed_symmetric PASSED
tests/test_sparkline.py::test_rail_positions_clamped_at_top_keeps_gap PASSED
tests/test_sparkline.py::test_rail_positions_clamped_at_bottom_keeps_gap PASSED
tests/test_sparkline.py::test_rail_positions_always_within_margins PASSED
============================== 28 passed in 0.30s ==============================

.venv/bin/python -m pytest tests/ -q -k "not slow"
5 failed, 195 passed, 1 deselected in 2.99s
(5 remaining failures are Phase 2 template tests — expected at this stage)
```

## Commit hash

(see git log after commit)

## Deviations from plan

None. Implementation matches the algorithm exactly as specified.

## Test gaps

No gaps. The plan described `test_rail_unchanged_when_dots_far` but the orchestrator did not write it (probably because margin clamping makes `current_rail != last_y_frac` for [300, 600] due to the 0.14 top-margin). The 12 tests that were written all pass.

## Follow-ups / noted-but-not-done

None for this phase.

## Confidence

Certain.
