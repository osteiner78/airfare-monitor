# 027 Phase 4 — record the deferred items

**Date:** 2026-08-17
**Plan:** `.agent/plans/027-refactor-scan-remediation.md`, Phase 4

## What I built

Documentation-only phase, no code changes. Added four deferred refactor
scan findings to `TODO.md`, each attached to the roadmap section the plan
named and carrying the trigger the report (`026-refactor-scan-all-codebase.md`)
assigned:

1. **#3 (`kayak.py` generic-machinery/heuristics split)** and **#2
   (`_build_detail_context` extraction)** and **#9 (`SearchOutcome`)** and
   **the JS execution-test harness** — all four added under
   "### Additional sources + expandable flight detail" (the Skyscanner /
   expandable-row roadmap item), as a new "Refactor prerequisites" sub-list:
   #3 and #9 framed as Skyscanner's opening moves (a split-before-second-source
   seam, and the observability-contract rewrite a new source forces),
   #2 and the JS harness framed as the expandable-row UI's opening moves.
2. **#10 (`db.py`'s `_connect()` boilerplate)** — added under "### Database
   size: normalise first, then compress the series" as a bundled-in item,
   per the plan's "bundled into the DB-size normalisation work" instruction.
3. **#12 (`tracker_sources` table)** — verified already present in the
   Skyscanner roadmap item ("Move to a `tracker_sources` table... before
   adding the second pair, not after."), matching the report's proposed
   refactor almost verbatim. No action taken, per the plan.

## Verification

No plan-specified `## Verification` commands for this phase (it has none —
unlike Phases 1–3, Phase 4 carries no `**Tests:**`/`**Verify:**` lines, since
it changes no code). Ran the full suite anyway as a sanity check that a
TODO.md-only change disturbed nothing:

```
$ docker exec airfare-monitor python -m pytest tests/ -k "not slow"
====================== 520 passed, 3 deselected in 38.88s ======================
```

(520 — identical to the count at the end of Phase 3. No test added, removed,
or affected, as expected for a docs-only change.)

## Deviations from the plan

None. Followed the plan's assignment of each finding to its named roadmap
section and trigger exactly.

## Test gaps / new tests

None — this phase specifies no tests, and none apply to a TODO.md edit.

## Follow-ups / noted, not done

None beyond what's now recorded in TODO.md itself (that's the point of this
phase — nothing here is meant to be actioned yet).

## CLAUDE.md

No update made. This phase didn't introduce new files, modules, patterns, or
gotchas discovered during implementation — it recorded roadmap decisions in
TODO.md, which is the correct home for deferred work; CLAUDE.md documents
current-state architecture and conventions, not a backlog.

## Confidence

**certain** — mechanical transcription of report findings into TODO.md at
the locations and with the triggers the plan specified; full suite
unaffected.

## Commit

See `git log` for the `[phase-4.1]`-tagged commit following this report.
