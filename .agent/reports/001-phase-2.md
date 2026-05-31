============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0 -- /Users/oliversteiner/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /Users/oliversteiner/Documents/code/airfare-monitor
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 14 items / 1 deselected / 13 selected

tests/test_fingerprint.py::test_nonstop_key_contains_four_pipe_separated_parts PASSED [  7%]
tests/test_fingerprint.py::test_nonstop_key_starts_with_source_name PASSED [ 15%]
tests/test_fingerprint.py::test_nonstop_key_contains_airline_and_flight_number PASSED [ 23%]
tests/test_fingerprint.py::test_multistop_key_joins_airlines_with_plus PASSED [ 30%]
tests/test_fingerprint.py::test_multistop_key_joins_flight_numbers_with_plus PASSED [ 38%]
tests/test_fingerprint.py::test_same_flight_result_produces_same_key_on_repeated_calls PASSED [ 46%]
tests/test_fingerprint.py::test_different_departure_times_produce_different_keys PASSED [ 53%]
tests/test_fingerprint.py::test_key_with_empty_airline_still_produces_four_parts PASSED [ 61%]
tests/test_sources.py::test_flight_result_dataclass_has_all_required_fields PASSED [ 69%]
tests/test_sources.py::test_google_flights_source_satisfies_search_source_protocol PASSED [ 76%]
tests/test_sources.py::test_all_sources_returns_nonempty_list PASSED     [ 84%]
tests/test_sources.py::test_google_flights_returns_empty_list_when_fli_raises_import_error PASSED [ 92%]
tests/test_sources.py::test_google_flights_returns_empty_list_when_search_raises_exception PASSED [100%]

======================= 13 passed, 1 deselected in 0.31s =======================
