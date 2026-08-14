# 024 — Phase 1 report: the certain one-liners

## What I built

1. **`api.py:42` and `api.py:106`** — both manual-trigger endpoints
   (`POST /api/trackers`, `POST /api/trackers/{id}/search`) now call
   `search_and_store(..., delay=False)`. Previously they relied on the
   default `delay=True`, so a Kayak-enabled, currently-due tracker could
   block the HTTP request for up to 15 minutes on the jitter sleep.
2. **`pages.py:907`** — `toggle_tracker_kayak` reads
   `tracker.get("kayak_enabled")` instead of `tracker["kayak_enabled"]`, so a
   request against an un-migrated `trackers` row degrades to "currently off"
   instead of raising `KeyError` (the same rule already applied everywhere
   else this column is read, per CLAUDE.md's Active-dev-vs-migration note).
3. **`google_flights.py`/`fast_flights.py`** — the `except ImportError`
   branch in `search()` now sets `self.last_error` (`"import failed: ..."`)
   and `self.last_error_level = "ERROR"` before returning `[]`, so a broken
   dependency import is distinguishable from a genuine zero-result search on
   `/monitor` — previously it returned `[]` with `last_error` left `None`,
   identical to a healthy empty search.
4. **`pages.py:551`** — the two hardcoded `60`s in
   `max_age_minutes = max(2 * (tracker["interval_minutes"] or 60), 60)` had
   different jobs (interval fallback vs. an independent staleness floor) and
   were at risk of being conflated. The first now reads
   `DEFAULT_INTERVAL_MINUTES` (imported from `backend.db`, already imported
   in this file); the second is now the named module-level constant
   `_MIN_SOURCE_STALENESS_FLOOR_MINUTES = 60`, placed next to `_BLEND_GROUPS`
   with a comment explaining why it must stay independent. Values are
   unchanged (both still resolve to 60 for the default case), so this is a
   pure rename with no behavior change.

## Tests added

The plan's "Tests (new)" section for this phase describes test scenarios in
prose rather than naming pre-written failing test files (unlike a typical
`/plan`-generated phase). I wrote five new tests matching those scenarios,
following each file's existing conventions, and verified each one fails for
the right reason against the pre-fix code (via `git stash` on the four
source files only, tests kept) before restoring the fix:

- `tests/test_api.py::test_post_search_calls_search_and_store_with_delay_false`
- `tests/test_api.py::test_post_trackers_calls_search_and_store_with_delay_false`
  (both assert the endpoint's `AsyncMock`-patched `search_and_store` — the
  `client` fixture already mocks it — was called with `delay=False`; more
  direct than intercepting `asyncio.sleep`, and precisely pins the one-token
  fix)
- `tests/test_kayak_scheduling.py::test_toggle_kayak_endpoint_survives_tracker_row_without_kayak_column`
  (mirrors the existing `search_and_store` un-migrated-row test's pattern:
  patches `backend.pages.get_tracker` to return a dict with `kayak_enabled`
  stripped)
- `tests/test_sources.py::test_google_flights_import_error_sets_last_error`
- `tests/test_fast_flights_source.py::test_fast_flights_import_error_sets_last_error`
  (both assert `last_error is not None`, contains `"import failed"`, and
  `last_error_level == "ERROR"`; fast_flights raises `ModuleNotFoundError`
  under the `sys.modules[...] = None` sentinel rather than bare
  `ImportError`, so the assertion checks the message prefix, not the
  exception class name)

Pre-fix failure output (all 5, right reason — `KeyError`/`AssertionError` on
the exact behavior being fixed, not a collection error):

```
FAILED tests/test_sources.py::test_google_flights_import_error_sets_last_error
FAILED tests/test_fast_flights_source.py::test_fast_flights_import_error_sets_last_error
FAILED tests/test_api.py::test_post_search_calls_search_and_store_with_delay_false
FAILED tests/test_api.py::test_post_trackers_calls_search_and_store_with_delay_false
FAILED tests/test_kayak_scheduling.py::test_toggle_kayak_endpoint_survives_tracker_row_without_kayak_column
5 failed in 2.08s
```

No pre-existing orchestrator-written test was modified, weakened, or
deleted.

## Verification output

```
$ docker exec -w /app airfare-monitor python -m pytest tests/ -k "not slow"
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /app
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.2
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 481 items / 3 deselected / 478 selected

478 passed, 3 deselected in 38.91s
```

478 = 473 baseline (Phase 0) + 5 new.

## Commit

`2cc7d6e` — "[phase-1] Fix four certain one-liners from the 022/023 code
review"

## Deviations from the plan

None in the fixes themselves. The plan's Phase 1 "Tests (new)" bullets are
scenario descriptions, not file paths naming pre-written tests (see below).

## Test gaps flagged / new tests added

**Not a plan gap, but worth recording:** unlike a typical `/plan`-generated
implementation plan, this code-review-remediation plan does not ship
pre-written failing test files per phase — each phase's "Tests (new)"
section is prose. I treated this plan's text as authoritative (per the
`/implement` skill's own instruction) and wrote the five tests myself,
matching the described scenarios as closely as possible, verifying each
against pre-fix code before trusting it. Flagging per the skill's
"discovery gap" provision rather than silently proceeding as if orchestrator
tests already existed.

One scenario in the plan ("asyncio.sleep is never called with a jitter
delay (monkeypatch to record)") was implemented differently than literally
described: the `client` fixture in `conftest.py` already replaces
`backend.scheduler.search_and_store` with an `AsyncMock` for every test using
it, so `asyncio.sleep` inside the real function is never reached from an
API-level test regardless. I asserted the mock's call kwargs
(`delay=False`) instead, which pins the exact one-line fix at the exact call
site more precisely than an `asyncio.sleep` spy would from outside a fully
mocked function.

## Follow-ups / noted-but-not-done

- Same Docker-only test environment note as Phase 0: no local `python` on
  `PATH`; ran everything via `docker exec -w /app airfare-monitor python -m
  pytest ...` against the live Active-dev bind mount.
- Phase 1 does not touch `CLAUDE.md` — that's explicitly Phase 6's job per
  the plan.

## Confidence rating

**certain** — all four fixes are exactly the one-token/one-constant changes
the plan specified, each new test was confirmed to fail for the right
reason pre-fix and pass post-fix, and the full suite is green with no
regressions.
