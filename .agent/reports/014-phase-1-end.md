# Report 014 — Phase 1 end

## What was built

- Added `_primary_delta(summary: dict) -> dict | None` to `backend/pages.py`. Iterates `[("3h", delta_3h), ("24h", delta_24h), ("start", delta_creation)]`; returns the first entry whose delta is non-None and `type in ("up","down")` as `{"period", "type", "amount"}`; else `None`.
- In `_enrich_summaries`, assigned `s["primary_delta"] = _primary_delta(s)` after the existing delta computations.

## Verification output

```
$ .venv/bin/python -m pytest tests/test_pages.py -k "primary_delta" -v
============================= test session starts ==============================
platform darwin -- Python 3.14.5, pytest-9.0.3
6 selected

tests/test_pages.py::test_primary_delta_prefers_3h PASSED
tests/test_pages.py::test_primary_delta_falls_back_to_24h PASSED
tests/test_pages.py::test_primary_delta_falls_back_to_start PASSED
tests/test_pages.py::test_primary_delta_skips_same PASSED
tests/test_pages.py::test_primary_delta_none_when_no_movement PASSED
tests/test_pages.py::test_primary_delta_carries_type_and_amount PASSED
6 passed in 0.22s

$ .venv/bin/python -m pytest tests/ -q -k "not slow"
207 passed, 4 failed (Phase 2 stubs), 1 deselected
```

The 4 remaining failures are Phase 2 tests that correctly fail against the current implementation.

## Commit

`ed95643` — [phase-1.1] add _primary_delta selector and wire into _enrich_summaries

## Deviations

None.

## Test gaps

None.

## Follow-ups

None.

## Confidence

certain
