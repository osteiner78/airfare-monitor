# 007 — Code Review Fixes: Start

**Date**: 2026-05-31
**Baseline**: 100 tests pass, 0 fail (`pytest tests/ -v -k "not slow"`)

## Scope

Implement fixes for the 4 important items from the code review:

- **I1** — `best_price` includes missing flights (`backend/pages.py:218`)
- **I2** — Duplicated timestamp-splitting code (`backend/pages.py:158-171, 182-196`)
- **I3** — Duplicate CSS rules (`frontend/static/app.css`)
- **I4** — `get_recent_logs` sorts by `id` instead of `created_at` (`backend/db.py:455`)

## Notes

- **S1** (`.gitignore` database protection): Already handled — `.gitignore` has both `data/` and `*.db`.
- **I5** (middleware perf): Negligible impact for personal tool, skipped per report guidance.
- **S2-S4**: Suggestions only, will assess after important fixes.

Success criteria: all existing tests still pass after fixes.
