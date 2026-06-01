# 009 Phase 2 Report — Wire colors into chart datasets + charts.js

## What was built

- Called `_assign_chart_colors(list(chart_datasets.keys()))` in `_build_detail_context` after the chart loop; set `entry["color"]` on each dataset entry; added `"flight_key_colors": flight_key_colors` to the returned context dict.
- Updated `charts.js` lines 27–28 to prefer `ds.color` over the index-based palette (`ds.color || colors[i % colors.length]`).

## Verification output

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
asyncio: mode=Mode.AUTO

collected 30 items

tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_keys_ever_in_top_n PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_tracker_with_no_snapshots PASSED
tests/test_chart_data.py::test_get_sticky_top_flight_keys_returns_empty_for_nonexistent_tracker PASSED
tests/test_chart_data.py::test_chart_datasets_limited_to_sticky_top_n PASSED
tests/test_chart_data.py::test_chart_dataset_includes_color_field PASSED
tests/test_chart_data.py::test_chart_dataset_color_is_first_palette_color_for_single_flight PASSED
tests/test_pages.py::test_dashboard_returns_200 PASSED
[... 21 more PASSED ...]
tests/test_pages.py::test_charted_row_carries_its_chart_color FAILED    (expected — Phase 3 not done)
tests/test_pages.py::test_charted_row_has_flight_key_data_attribute FAILED (expected)
tests/test_pages.py::test_missing_row_has_no_row_color FAILED            (expected)

27 passed, 3 failed
```

## Commit

`20164f0` — `[phase-2.1] wire _assign_chart_colors into context; charts.js prefers server color`

## Deviations

None. The 3 failures are Phase 3 tests (template/CSS not yet applied), expected at this stage.

## Confidence

certain
