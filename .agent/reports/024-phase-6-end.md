# 024 Phase 6 — documentation and standing checks

**Plan:** `.agent/plans/024-code-review-remediation.md`, Phase 6
**Date:** 2026-08-13

---

## What was built

Doc-only phase, no code changes. Checked every item the plan lists against
the current state of `CLAUDE.md`/`TODO.md` before editing — phases 1–5 had
already landed most of the required documentation as part of their own
reports (test count, `flight_key` variant-name resolution, the render
worker's real wait count, `_relative_minutes`/`base.html` pairing), so this
phase closed the remaining gap rather than writing all six items from
scratch.

**CLAUDE.md:**
1. Extended the "Kayak wiring into the main search cycle" bullet to name all
   five `search_and_store(..., delay=False)` call sites explicitly
   (`api.py::create_tracker_endpoint`, `api.py::search_now_endpoint`,
   `pages.py::add_tracker`, `pages.py::search_now`, `pages.py::refresh_all`)
   instead of the previous "manual/test triggers" generality.
2. Added a new bullet for `_AIRLINE_NAME_TO_CODE`'s second job (F2) — this
   was the one item genuinely missing. The "Tracker filter sidebar" bullet
   (written in Phase 5) already said "see `_AIRLINE_NAME_TO_CODE`'s
   second-job note above", but no such note existed anywhere above it; Phase
   5's own report flagged this as explicitly deferred to Phase 6. The new
   bullet documents the two consumers in `pages.py`
   (`_airline_code_from_name` for the logo lookup, `_airline_identity` for
   facet grouping) and why they deliberately diverge on
   `LOGO_UNAVAILABLE_CODES` — the logo lookup gates on it (no logo image ->
   fall back to the name), the identity lookup does not (no logo image
   shouldn't stop two rows for the same carrier from merging into one filter
   group).

Confirmed already correct and left untouched: test count (`509 passed, 3
deselected`, matches Phase 5's final count), the `flight_key` variant-name
limitation + Phase 4 resolution, the render worker's real-wait accounting
(Phase 3's bullet already gives the exact per-wait constants), and the
`_relative_minutes`/`updateRelativeTimes` pairing note.

**TODO.md:**
1. Ticked the "Audit the codebase for cross-file invariants" roadmap item and
   appended a "Done 2026-08-13" note pointing at `022-code-review.md`,
   `023-code-review-cross-file-invariants.md`, and this plan's six phases.
2. Recorded the two standing data checks under that same item (rows outside
   `[depart_date, depart_date+1]` — N4/A8; same-carrier/same-clock pairs one
   day apart with departure hour >= 3 — F6), noting both returned zero as of
   024's own verification.
3. Added N7 (stale source silently vanishes from the detail page) as a new
   bullet under `#### Table` in the "Tracker details" section — that's the
   part of the UI list actually describing the detail page's results
   presentation, which is where N7 lives.
4. Added a bullet to "Additional sources + expandable flight detail" for
   codeshare pairs as a second identity fork (023's architectural finding) —
   noted why it belongs with that roadmap item specifically: codeshares are
   the same "one itinerary, several sellers" shape the expandable per-row
   detail view is designed to show, and unlike the Phase 4 name-variant fork
   it can't be solved by a name->code map since the two carriers are
   genuinely different sellers.

## Verification

The plan's Phase 6 section has no `**Verify:**` line (unlike Phases 1–5) —
it's documentation-only and touches no code, so there's no test command to
run. Confirmed no source files changed:

```
$ git status
On branch 017-kayak-source
Changes not staged for commit:
        modified:   CLAUDE.md
        modified:   TODO.md
Untracked files:
        .agent/reports/024-phase-1-end.md
```

Only `CLAUDE.md` and `TODO.md` are modified. `git diff --stat`:

```
 CLAUDE.md |  3 ++-
 TODO.md   | 41 ++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 42 insertions(+), 2 deletions(-)
```

## Deviations from the plan

None.

## Test gaps flagged / new tests added

None — doc-only phase, no test-bearing behavior changed.

## Follow-ups / noted but not done

- `.agent/reports/024-phase-1-end.md` is untracked in git (Phase 1's own
  commit `2cc7d6e` never included it, unlike every other phase's end
  report). Out of scope for Phase 6 — flagging rather than committing it
  silently as part of an unrelated phase's commit.
- `pages.py::_airline_identity` still duplicates the `AIRLINE_NAME_TO_CODE`
  lookup that `fingerprint.py::_normalize_airline` performs (noted in Phase
  4 and Phase 5's reports too) — a real duplication, but refactoring it is
  outside this plan's scope, which explicitly excludes anything not named in
  a finding.

## Confidence rating

**certain.** Every item the plan lists for Phase 6 was checked against the
actual current file content (not assumed from the plan text), and the one
genuine gap (`_AIRLINE_NAME_TO_CODE`'s second-job note, which Phase 5's
report explicitly flagged as deferred here) is now filled in, closing the
dangling forward-reference.
