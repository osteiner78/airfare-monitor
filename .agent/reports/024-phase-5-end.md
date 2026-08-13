# 024 Phase 5 — display stability

**Plan:** `.agent/plans/024-code-review-remediation.md`, Phase 5
**Date:** 2026-08-13

---

## What was built

**Task 1 (A6/F3) — airline checkbox identity is now stable across blend
composition.** `backend/pages.py::_build_detail_context`: `airline_groups`
entries now carry a `"key"` field (the group's `_airline_identity(name)`
value, computed once at group creation). `window.allFlights`'s `f["airline"]`
and the sidebar checkbox `value` (`detail_page.html:81`) both switched from
`airline_groups[...]["name"]` (the display name — unstable, since it's seeded
from whichever source's row is first in that cycle's price-ordered blend) to
`airline_groups[...]["key"]` (stable, since `_airline_identity` returns the
same mapped IATA code — or the same casefolded name for an unmapped carrier —
regardless of which variant text arrived first). The visible label keeps
using `a.name`; only the `value`/filter-matching identity changed.

**Task 2 (A12/F10) — a source can no longer appear twice in a merged row.**
`_group_duplicate_price_rows`: the `sources` list append became
`existing["sources"] = list(dict.fromkeys(existing["sources"] + [flight.get("source")]))`,
per the plan's specified method (order-preserving dedup).

**Task 3 (A11/F4, test only) — `_relative_minutes` boundary table.** No code
change (the function and its comment naming `base.html::updateRelativeTimes`
as counterpart already existed, and its bucketing was independently confirmed
to match that JS function). Added the boundary-value parametrised test the
plan calls for.

---

## A test conflict, flagged and resolved with explicit approval

Before writing code, I found that Phase 5's task 1 directly conflicts with
three **pre-existing**, plan-011-owned tests in `tests/test_filters.py`, all
three pinning the *old* contract (checkbox value / `window.allFlights.airline`
== the display name):

- `test_airline_checkbox_value_is_airline_name` (asserted `value="Vueling"`)
- `test_all_flights_entry_includes_airline` (asserted `airline == "Vueling"`)
- `test_airlines_sorted_by_best_price_ascending` (asserted `value="Vueling"` /
  `value="Iberia"` ordering)

This is a genuine assertion-level conflict, not a fixture-input mismatch —
CLAUDE.md's own precedent for this project (plan 019/020, plan 024 Phase 4)
only ever adapted old tests' *inputs*, leaving assertions untouched, and the
one prior case that needed an assertion rewrite is explicitly recorded as
having required the user's sign-off first. I stopped, described the conflict,
and asked; the user approved rewriting the assertions. All three were
rewritten (renamed to describe the new contract, assertions updated to expect
the stable identity key — `"VY"` for Vueling, which turned out to be **mapped**
in `AIRLINE_NAME_TO_CODE`, not unmapped as my first draft's comments assumed;
corrected before the final run) — see the diff in `tests/test_filters.py`.

## New tests added

All in `tests/test_filters.py`, plan-specified scenarios plus one discovery-gap
addition:

- `test_airline_checkbox_value_is_byte_identical_across_blend_composition` —
  the plan's named test: builds the detail context twice (a Kayak-only
  snapshot, then a blended Kayak+Google snapshot for the same flight, one
  `"LATAM AIRLINES"` and one `"LATAM"`) and asserts the rendered checkbox
  value is byte-identical across both.
- `test_merged_row_lists_each_source_once` — HTTP-level smoke test: two rows
  from the same source landing in one merge bucket must not render
  `"Kayak, Kayak"`.
- `test_group_duplicate_price_rows_dedupes_sources` — direct unit test of the
  pure function (**discovery gap, flagged**: the plan didn't name a unit-level
  test for this, only the HTTP-level check implied by "Test: ..." at the top
  of Phase 5; added because the pure-function form pins the exact fix
  mechanism without depending on template markup).
- `test_relative_minutes_boundaries` — parametrised over
  `0, 1, 59, 60, 1439, 1440`, exactly as the plan specifies, with a comment
  naming `base.html::updateRelativeTimes` as the counterpart.

## Verification

### Focused run

```
$ docker exec airfare-monitor python -m pytest tests/test_filters.py -v
...
35 passed in 7.26s
```

### Full suite

```
$ docker exec airfare-monitor python -m pytest tests/ -q -k "not slow"
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 84%]
........................................................................ [ 99%]
.....                                                                    [100%]
509 passed, 3 deselected in 297.69s (0:04:57)
```

Baseline immediately before this phase (end of Phase 4): `500 passed, 3
deselected`. The delta is exactly the 9 tests added by this phase (3 new named
tests + 6 parametrised `_relative_minutes` cases); the 3 rewritten tests kept
their (new) assertions, not added new ones.

### Live smoke test

```
$ docker exec airfare-monitor python -c "... GET /trackers/{20,21,22} ..."
20 200
21 200
22 200
```

Checked the actual rendered markup on tracker 20 (live production data, real
Kayak+Google blend): checkbox values are now IATA codes (`TP`, `IB`, `UX`,
`AZ`, `AD`, `LA`, ...) while `data-airline` attributes are unchanged raw
display names (`Aerolineas Argentinas`, `Aeromexico`, ...) — confirming the
split between the stable filtering identity and the unaffected display
attribute.

---

## Deviations from the plan

None in substance. The only departure is process, not content: the plan's
task 1 doesn't mention updating any existing test, but implementing it
necessarily broke three pre-existing ones; those were rewritten with the
user's explicit approval (see above) rather than silently, which is not a
deviation from the plan's *intent* but is worth recording since it wasn't
anticipated in the plan text.

## Test gaps flagged / new tests added

- `test_group_duplicate_price_rows_dedupes_sources` — discovery-gap addition,
  reasoning above.
- No plan gaps: every scenario the plan named in prose for Phase 5 has a
  corresponding test.

## Follow-ups / noted but not done

- `pages.py::_airline_identity` still duplicates the `AIRLINE_NAME_TO_CODE`
  lookup that `fingerprint.py::_normalize_airline` also performs (noted as a
  follow-up in the Phase 4 report too). Phase 6 is documentation-only per the
  plan, so this stays a follow-up, not something this phase touches.
- `_AIRLINE_NAME_TO_CODE`'s undocumented second job as the facet-grouping
  identity (F2) is explicitly deferred to Phase 6 (doc-only) — not addressed
  here, per the plan.

## CLAUDE.md updates

- Rewrote the "Tracker filter sidebar" bullet: the checkbox value / `f["airline"]`
  are now the stable `_airline_identity` key, not the display name; explained
  why (blend-composition instability + the `localStorage` re-check bug), and
  that `_airline_identity` returns an uppercase code as-is for a mapped
  carrier (unlike `fingerprint.py`'s casefolding `_normalize_airline`).
- Added a bullet for the `_group_duplicate_price_rows` sources dedup.
- Added a bullet pinning `_relative_minutes` / `base.html::updateRelativeTimes`
  as counterparts that must be changed together.
- Test count `500` → `509`.

## Confidence rating

**likely-good.** All plan-specified behavior is implemented and tested, the
full suite is green, and the fix was additionally verified against live
production data (not just fixtures). The "likely" qualifier is only because
the byte-identical pinning test uses synthetic snapshots rather than the
exact live LATAM/LATAM-Airlines rows from Phase 4's report — those weren't
reused since this test needs to control *which* snapshot is Kayak-only vs.
blended, which the live data's actual history doesn't cleanly provide.
