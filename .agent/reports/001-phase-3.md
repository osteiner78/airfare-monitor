============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0 -- /Users/oliversteiner/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /Users/oliversteiner/Documents/code/airfare-monitor
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 15 items

tests/test_api.py::test_get_trackers_returns_empty_list_initially PASSED [  6%]
tests/test_api.py::test_post_trackers_returns_201_with_tracker_id PASSED [ 13%]
tests/test_api.py::test_post_trackers_adds_tracker_visible_in_list PASSED [ 20%]
tests/test_api.py::test_get_tracker_by_id_returns_tracker PASSED         [ 26%]
tests/test_api.py::test_get_tracker_returns_404_for_unknown_id PASSED    [ 33%]
tests/test_api.py::test_patch_tracker_sets_active_to_false PASSED        [ 40%]
tests/test_api.py::test_delete_tracker_returns_204 PASSED                [ 46%]
tests/test_api.py::test_delete_tracker_removes_tracker_from_list PASSED  [ 53%]
tests/test_api.py::test_delete_tracker_returns_404_for_unknown_id PASSED [ 60%]
tests/test_api.py::test_get_history_returns_empty_flights_for_new_tracker PASSED [ 66%]
tests/test_api.py::test_post_search_returns_200 PASSED                   [ 73%]
tests/test_api.py::test_post_trackers_returns_422_when_origin_is_missing PASSED [ 80%]
tests/test_api.py::test_post_trackers_returns_422_when_destination_is_missing PASSED [ 86%]
tests/test_api.py::test_post_trackers_returns_422_when_depart_date_is_missing PASSED [ 93%]
tests/test_api.py::test_post_trackers_returns_422_when_depart_date_format_is_invalid PASSED [100%]

============================== 15 passed in 0.34s ==============================
