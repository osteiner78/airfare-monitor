# 027 Phase 2 — one strip-block algorithm

**Date:** 2026-08-17
**Plan:** `.agent/plans/027-refactor-scan-remediation.md`, Phase 2 (#1)

## What I built

Extracted `_strip_blocks(lines, start_pred, end_pred, max_lines) -> list[str]`
in `backend/sources/kayak.py` as a pure, module-level function carrying the
scan loop shared by `_strip_self_transfer_rows`, `_strip_nearby_airport_promos`
and `_strip_placements`: from a line matching `start_pred`, search up to
`max_lines` ahead for a line matching `end_pred`; if found, drop the whole
span inclusive; if not, drop only the start line rather than guessing where
the block ends. Each of the three original functions is now a thin wrapper
binding its own predicates/bound to `_strip_blocks`, with its docstring and
early-exit guard kept verbatim (unchanged text, unchanged position relative
to the `lines = body_text.split("\n")` split) per the plan's explicit
instruction not to collapse the three docstrings into one.

No behavior changed: `_strip_placements`' early-exit guard still runs after
the split (`lines = body_text.split("\n"); if not any(...)`), while the other
two still guard on the raw `body_text` before splitting — that pre-existing
difference was preserved rather than normalized, since normalizing it was
outside this phase's scope.

## Verification

This phase adds no new tests — per the plan, "Tests: unchanged... must stay
green untouched. That is the whole proof." Baseline (before the edit) and
post-edit runs, both inside the `airfare-monitor` container:

Baseline (pre-refactor):
```
$ docker exec airfare-monitor python -m pytest tests/test_kayak_placements.py tests/test_kayak_offroute_prices.py tests/test_kayak_source.py -v -k "not slow"
====================== 106 passed, 1 deselected in 1.92s =======================
```

Post-refactor, identical command:
```
====================== 106 passed, 1 deselected in 1.68s =======================
```

Full suite post-refactor:
```
$ docker exec airfare-monitor python -m pytest tests/ -k "not slow"
====================== 517 passed, 3 deselected in 40.05s ======================
```

(517 matches the count at the end of Phase 1 — no tests added or removed
this phase.)

## Deviations from the plan

None. `end_pred` in `_strip_blocks` is the positive form ("is this the
terminator line") rather than each original's negated `while` condition
("is this NOT the terminator") — an equivalent restatement needed to express
one shared loop, not a behavior change; verified by the identical pass count
above.

## Test gaps / new tests

None. The plan explicitly scoped this phase to zero new tests.

## Follow-ups / noted, not done

- `_strip_placements`'s early-exit guard runs after splitting into `lines`
  while the other two guard on `body_text` before splitting. Left as-is
  (pre-existing inconsistency, outside this phase's scope) — noting in case
  a future pass wants to normalize it.

## Confidence

**certain** — pure mechanical extraction, identical pass counts before and
after, full suite green.

## Commit

See `git log` for the `[phase-2.1]`-tagged commit following this report.
