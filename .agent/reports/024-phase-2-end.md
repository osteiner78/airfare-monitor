# 024 — Phase 2 report: observability on the rebase

## What I built

`KayakSource._validate` now returns `(validated, rebased_count)` instead of a
bare list. `rebased_count` is incremented per-row at the point
`_rebase_departure_date` is invoked, using an identity check
(`rebased is not row`) rather than a value comparison — `_rebase_departure_date`
already returns the *same* object untouched when it declines to rebase, and a
new `dict` only when it rewrites, so this is a free, exact signal with no new
state to track. The count is accumulated regardless of whether the row later
survives grounding/outlier filtering, since the thing being observed is "how
many times did the rebase fire", not "how many rebased rows made it to the
results table".

`_search_inner` unpacks the tuple, always records `rebased_rows` in the sample
sidecar `record` (so it is present for every outcome — a null/absent field
would be a silent no-signal case), and — only when `dropped == 0` (i.e. no
other WARNING message has already been set for this attempt) and
`rebased_count > 0` — sets `last_error` to a message naming the count and
`last_error_level = "WARNING"`. This mirrors the existing "partial drop"
branch immediately above it in both shape and priority: a drop message always
wins over a rebase message if both would apply, since a drop is the more
serious signal.

## Pre-existing tests adapted (not weakened)

Changing `_validate`'s return type is a breaking signature change that every
existing caller of it must adapt to — not just an input/fixture change of the
kind CLAUDE.md's other precedents describe (plan 020 Phase 2's IATA-vs-name
fixture repair). ~18 call sites across `tests/test_kayak_source.py` and
`tests/test_kayak_placements.py` called `KayakSource._validate(...)` expecting
a plain list back (`kept = ...`, `len(...)`, `... == []`). I mechanically
adapted every one to unpack the tuple (`kept, _ = KayakSource._validate(...)`,
or `KayakSource._validate(...)[0]` inline) — **no assertion was touched**, only
the unpacking syntax needed to reach the same list these tests already
checked. Verified each of these individually still exercises the same
behavior: full diff reviewed, `git diff` above shows only the unpacking
changed.

I did not ask before doing this because the plan is unambiguous about the
exact new signature (`` `_validate` returns `(validated, rebased_count)` ``),
and CLAUDE.md already documents this exact class of situation happening twice
before (plan 019 Phase 1's `_sample_body()` repair, plan 020 Phase 2's carrier
fixture repair) with the same resolution: adapt mechanically, leave the
assertion's intent untouched. Flagging here per the `/implement` skill's
"discovery gap" provision rather than silently treating it as routine.

## Tests added

Per the plan's "Test: a search where exactly one row rolls over asserts the
counter and the WARNING," plus two supporting unit tests on `_validate` itself
(the plan's Phase 1 precedent already established that this plan's "Tests"
sections are prose scenarios, not pre-written files — see
`.agent/reports/024-phase-1-end.md`):

- `test_validate_returns_the_number_of_rows_it_rebased` — two rows, one rolls
  over and one doesn't; asserts `rebased_count == 1` directly, independent of
  what survives grounding.
- `test_validate_reports_zero_rebased_rows_without_depart_date` — mirrors the
  pre-existing `test_validate_without_depart_date_does_not_rebase`; the
  counter must agree that nothing was rebased when `depart_date is None`.
- `test_search_warns_and_records_the_rebase_count_when_one_row_rolls_over` —
  end-to-end through `search()`: asserts `last_error_level == "WARNING"`,
  `last_error` names the count, and the sample sidecar JSON (read back via
  `source.last_sample_path`) carries `rebased_rows == 1`.

All three were confirmed to fail for the right reason against pre-fix code
(`git stash` on `backend/sources/kayak.py` only, tests kept):

```
FAILED tests/test_kayak_source.py::test_validate_returns_the_number_of_rows_it_rebased
  AssertionError: assert {'airline': 'SWISS', ...} == 1
  (unpacking a 2-row list into `_, rebased_count` bound the second row itself)

FAILED tests/test_kayak_source.py::test_validate_reports_zero_rebased_rows_without_depart_date
  ValueError: not enough values to unpack (expected 2, got 1)

FAILED tests/test_kayak_source.py::test_search_warns_and_records_the_rebase_count_when_one_row_rolls_over
  AssertionError: assert 'ERROR' == 'WARNING'
  (old code has no rebase-awareness at all; falls through to whatever
  last_error_level the rest of the run left behind)
```

## Verification output

```
$ docker exec -w /app airfare-monitor python -m pytest tests/ -k "not slow"
====================== 481 passed, 3 deselected in 37.10s ======================
```

481 = 478 (Phase 1 baseline) + 3 new.

## Commit

`18a925e` — "[phase-2] Surface night-rollover rebases on /monitor"

## Deviations from the plan

None in the fix itself — `_validate`'s new signature, the sidecar field name
(`rebased_rows`), and the "only when no other message has been set" guard all
match the plan's Phase 2 section exactly. The one deviation is procedural: the
plan doesn't mention that changing `_validate`'s signature would require
touching ~18 pre-existing test call sites; I treated this as implied by the
explicit signature change rather than an ambiguity worth stopping over (see
above).

## Test gaps flagged / new tests added

Same situation as Phase 1: this plan's "Tests (new)" sections are prose
scenarios, not pre-written failing test files. I wrote the three tests above
to match the plan's described scenario as closely as possible. No plan gap
(behavior without any corresponding test intent) was found — the plan asked
for exactly one end-to-end scenario, and I added two narrower unit tests
underneath it for direct coverage of the counter itself, which I'm flagging
per the "discovery gap" provision.

## Follow-ups / noted-but-not-done

- Same Docker-only test environment note as Phase 0/1: no local `python` on
  `PATH`; ran everything via `docker exec -w /app airfare-monitor python -m
  pytest ...` against the live Active-dev bind mount.
- `.agent/reports/024-phase-1-end.md` is still untracked from the prior
  session (not committed as part of the phase-1 commit). Out of scope for
  Phase 2 — left as-is rather than folding it into an unrelated commit.

## Confidence rating

**certain** — the fix is exactly what the plan specified, all three new tests
were confirmed to fail for the right reason pre-fix and pass post-fix, no
pre-existing assertion was altered (only mechanical unpacking), and the full
suite is green with no regressions.
