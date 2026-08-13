# 024 — Phase 0 report: land the working tree

## What I built

Phase 0 has no code deliverable — it is the "independent read that code never
got" for eight files left uncommitted by the 022/023 review pass, followed by
committing them as their own change, separate from any remediation work.

I reviewed the full diff of every uncommitted file:

- `backend/sources/kayak.py` — `_rebase_departure_date` (bounded to exactly
  `depart_date + 1 day` and hour `< _NIGHT_ROLLOVER_CUTOFF_HOUR (3)`),
  threaded through `_validate(rows, body_text, depart_date)` and `search()`.
- `backend/pages.py` — `_AIRLINE_NAME_TO_CODE` gains `"ITA": "AZ"`; the
  airline facet-grouping loop now groups by `_AIRLINE_NAME_TO_CODE`-mapped
  identity instead of raw name, with a naturally-cased name preferred over
  an ALL-CAPS one for display; a new `_relative_minutes` Jinja filter
  (`relative_minutes`) buckets minutes the same way `base.html`'s
  `updateRelativeTimes()` does.
- `frontend/static/filters.js` — airline filter persistence flipped to store
  the *unchecked* set in `localStorage` rather than the *checked* set, so an
  airline absent from a prior save (new, or renamed by casing) defaults to
  visible instead of vanishing.
- `frontend/templates/partials/detail_page.html`,
  `results_table.html` — staleness badges now render through the new
  `relative_minutes` filter instead of a raw `NN min ago` literal.
- `tests/test_kayak_source.py` — 11 new tests covering
  `_rebase_departure_date` directly (shift, overnight-arrival delta,
  untouched cases, cutoff-hour boundary, >1-day guard, unparseable input),
  `_validate`'s new `depart_date` parameter (with and without it), and
  `search()`'s end-to-end wiring.
- `CLAUDE.md`, `TODO.md` — one new note documenting the rollover decision;
  one new TODO item (actively searching next-day early-morning departures,
  explicitly deferred, scoped, and flagged as doubling Kayak request volume).
- `.agent/plans/024-code-review-remediation.md`,
  `.agent/reports/022-code-review.md`,
  `.agent/reports/023-code-review-cross-file-invariants.md` — untracked,
  added as-is (the review reports and the plan this report is part of).

Nothing in the diff looked out of scope, unbounded, or inconsistent with the
plan's characterization of it. The rollover fix is narrowly bounded (exact
+1-day, hour cutoff, single-day only, unparseable-passthrough) and matches
CLAUDE.md's account of the user's stated intent. The airline-grouping fix
reuses an existing map rather than introducing a new one. The filters.js
change fixes a real bug class (silently-vanishing airlines) with a minimal
inversion of what gets persisted.

## Verification output

```
$ docker exec -w /app airfare-monitor python -m pytest tests/ -k "not slow"
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /app
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.2
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 476 items / 3 deselected / 473 selected

tests/test_airline_logo.py ...........                                   [  2%]
tests/test_api.py ...............                                        [  5%]
tests/test_best_price.py ...                                             [  6%]
tests/test_best_source.py ......                                         [  7%]
tests/test_blended_sources.py ........                                   [  9%]
tests/test_chart_colors.py ........                                      [ 10%]
tests/test_chart_data.py ..........                                      [ 12%]
tests/test_chart_sticky_missing.py ...                                   [ 13%]
tests/test_db.py .....................                                   [ 17%]
tests/test_delta.py ......                                               [ 19%]
tests/test_duplicate_price_rows.py ....                                  [ 20%]
tests/test_fallback_source.py .....                                      [ 21%]
tests/test_fast_flights_source.py ..............                         [ 24%]
tests/test_filters.py ..........................                         [ 29%]
tests/test_fingerprint.py ...............                                [ 32%]
tests/test_kayak_cadence.py ........                                     [ 34%]
tests/test_kayak_currency.py ........                                    [ 36%]
tests/test_kayak_dedupe_and_startup.py ...............                   [ 39%]
tests/test_kayak_offroute_prices.py ..................                   [ 43%]
tests/test_kayak_placements.py ..........                                [ 45%]
tests/test_kayak_render_config.py ..................                     [ 49%]
tests/test_kayak_render_subprocess.py ........                           [ 50%]
tests/test_kayak_samples.py .........                                    [ 52%]
tests/test_kayak_scheduling.py ......................                    [ 57%]
tests/test_kayak_source.py ............................................. [ 66%]
.............................                                            [ 72%]
tests/test_kayak_timeout_budget.py ....                                  [ 73%]
tests/test_logging.py ......                                             [ 75%]
tests/test_normalization.py ......                                       [ 76%]
tests/test_notification_log.py ....                                      [ 77%]
tests/test_notifications.py ........                                     [ 78%]
tests/test_pages.py ..................................................   [ 89%]
tests/test_pages_multi_source.py ..........                              [ 91%]
tests/test_source_degradation.py .......                                 [ 93%]
tests/test_sources.py .....                                              [ 94%]
tests/test_sparkline.py ............................                     [100%]

====================== 473 passed, 3 deselected in 36.77s ======================
```

Matches the plan's stated baseline (`473 passed, 3 deselected`) exactly.

```
$ git status
On branch 017-kayak-source
nothing to commit, working tree clean
```

## Commit hash

`aa61992` — "Land pre-review working tree: night-rollover rebase, airline
grouping fix, relative-time filter"

(Note: the plan's own CLAUDE.md ledger for this landed code — test count,
the `flight_key` note, etc. — is explicitly Phase 6's job, not Phase 0's; I
did not touch it here.)

## Deviations from the plan

None. Phase 0 was executed exactly as specified: review, then one commit,
no code changes.

## Test gaps flagged / new tests added

None. No test writing was in scope for this phase; the 11 tests in the diff
were already present in the uncommitted working tree and were reviewed, not
authored, in this phase.

## Follow-ups / noted-but-not-done

- Environment note for future sessions: this host has no `python`/`conda` on
  `PATH` and no local venv for the project; `pytest`/`pytest-asyncio` are
  only available inside the running `airfare-monitor` Docker container
  (already installed there — did not need `pip install -r
  requirements-dev.txt`). Since this project is Active dev
  (`.:/app` bind mount), running tests via `docker exec -w /app
  airfare-monitor python -m pytest ...` reflects the live working tree with
  no rebuild needed.
- The plan's `TODO.md` new item ("actively search next-day early-morning
  departures") is itself scoped as a deferred, not-yet-planned feature — no
  action needed now, flagging only so it isn't mistaken for something this
  phase should have addressed.

## Confidence rating

**certain** — the diff review found nothing to push back on, the suite
matches the plan's exact expected baseline, and the commit is a clean,
isolated landing with no code changes of my own.
