# 008 Phase 1 Start Report

## Scope
Add the `_airline_code` Jinja filter to `backend/pages.py` and create `frontend/templates/partials/macros.html` with the `airline_logo` macro. No template wiring yet — the macro is created but not referenced by any existing template.

## Tests expected to turn green
All 11 tests in `tests/test_airline_logo.py`:
- 5 NEW-BEHAVIOR tests (valid code extraction, case, whitespace, alphanumeric)
- 6 FAILURE-MODE tests (empty, None, 3-digit, overlong, unicode, blacklisted)

## Pre-work observations
- `backend/pages.py` already imports nothing from `re`; need to add `import re` at top.
- Filter registration pattern is clear: `_env.filters["format_date"] = _format_date` at line 53 — adding `_env.filters["airline_code"] = _airline_code` right after.
- Baseline: 100 passed, 1 deselected.
- All 11 Phase 1 tests currently fail with `ImportError: cannot import name '_airline_code'` — correct pre-implementation state.
- Non-regression anchors (existing test_pages.py + test_db.py tests) all pass.
- `test_results_table_falls_back_to_name_when_code_invalid` already passes (current template renders airline name text).
- `test_summary_still_returns_min_best_price` passes (best_price logic unchanged).
