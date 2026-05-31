============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0 -- /Users/oliversteiner/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/oliversteiner/Documents/code/airfare-monitor
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 18 items

tests/test_db.py::test_wal_mode_enabled_after_init PASSED                [  5%]
tests/test_db.py::test_trackers_table_exists_after_init PASSED           [ 11%]
tests/test_db.py::test_snapshots_table_exists_after_init PASSED          [ 16%]
tests/test_db.py::test_flight_prices_table_exists_after_init PASSED      [ 22%]
tests/test_db.py::test_create_tracker_returns_dict_with_id PASSED        [ 27%]
tests/test_db.py::test_create_tracker_stores_all_provided_fields PASSED  [ 33%]
tests/test_db.py::test_list_trackers_returns_empty_list_when_no_trackers_exist PASSED [ 38%]
tests/test_db.py::test_get_tracker_returns_tracker_by_id PASSED          [ 44%]
tests/test_db.py::test_update_tracker_sets_active_to_false PASSED        [ 50%]
tests/test_db.py::test_delete_tracker_removes_the_row PASSED             [ 55%]
tests/test_db.py::test_delete_tracker_cascades_to_snapshots PASSED       [ 61%]
tests/test_db.py::test_create_snapshot_returns_dict_with_id PASSED       [ 66%]
tests/test_db.py::test_get_price_history_returns_empty_for_tracker_with_no_snapshots PASSED [ 72%]
tests/test_db.py::test_get_tracker_summaries_returns_empty_list_when_no_trackers PASSED [ 77%]
tests/test_db.py::test_get_tracker_returns_none_when_id_does_not_exist PASSED [ 83%]
tests/test_db.py::test_get_tracker_returns_none_for_zero_id PASSED       [ 88%]
tests/test_db.py::test_get_tracker_returns_none_for_negative_id PASSED   [ 94%]
tests/test_db.py::test_delete_tracker_on_missing_id_does_not_raise PASSED [100%]

============================== 18 passed in 0.12s ==============================
