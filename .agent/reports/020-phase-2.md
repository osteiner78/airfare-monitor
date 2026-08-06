# Plan 020 — Phase 2 report: ground the airline component of the identity

## What was built

- `KayakSource._airline_grounded(airline, body_text) -> bool` (static
  method, next to `_price_grounded`/`_time_grounded`): the extracted
  carrier must appear in the rendered page, normalised the same way
  `make_flight_key` normalises (casefold, collapse whitespace), so a pure
  case difference is never treated as a fabrication.
- One exception: `"multiple airlines"` (casefolded) is treated as
  unconditionally trusted rather than substring-matched — it's Kayak's own
  generated row label for a multi-carrier self-transfer itinerary (Decision
  3, verified 8 occurrences in the real captured body), not text a model
  could have copied from elsewhere on the page and mis-bound to a row, so
  it doesn't carry the same fabrication risk a named carrier does.
- Wired into `_validate`, next to the existing `_price_grounded`/
  `_time_grounded` checks, same drop-and-log-at-WARNING behaviour.

## Blocker hit and resolution

Implementing the check as specified broke two **pre-existing, orchestrator-
owned tests** in `tests/test_kayak_source.py` (from an earlier plan, not
this one):
- `test_validate_keeps_row_whose_price_uses_comma_decimals` — row airline
  `"LX"` (an IATA code) against a body printing the full name `"SWISS"`.
- `test_validate_drops_price_wildly_outside_the_band_of_other_rows` — rows
  used placeholder airlines `"A"`/`"B"`/`"C"`/`"D"` that appeared nowhere in
  the body at all, so every row was dropped by the new check before the
  outlier-price logic the test exists to exercise could even run.

Both predate plan 020 and used throwaway airline values never meant to
match page text, since airline grounding didn't exist when they were
written. Per this project's test-ownership rule I stopped and asked rather
than editing them myself. The user (Oliver) chose to adapt the two
fixtures directly and committed it while I was waiting on the question:
`785d169 "Adapt two fixtures for airline grounding; record the code-vs-name
risk"` (2026-08-06). Both fixtures now use airline names that are actually
printed in their bodies; both tests' original assertions and intent
(comma-decimal price parsing; outlier-price filtering) are unchanged. No
test in the suite was modified by me.

## Verification

`pytest tests/test_kayak_placements.py -v`:

```
collected 10 items

tests/test_kayak_placements.py::test_strips_the_expedia_placement_block_from_a_real_captured_body PASSED [ 10%]
tests/test_kayak_placements.py::test_placement_price_does_not_survive_stripping PASSED [ 20%]
tests/test_kayak_placements.py::test_genuine_result_rows_survive_stripping PASSED [ 30%]
tests/test_kayak_placements.py::test_strips_every_placement_not_just_the_first PASSED [ 40%]
tests/test_kayak_placements.py::test_body_without_placements_is_returned_unchanged PASSED [ 50%]
tests/test_kayak_placements.py::test_search_does_not_extract_a_placement_price PASSED [ 60%]
tests/test_kayak_placements.py::test_validate_drops_row_whose_airline_is_absent_from_rendered_text PASSED [ 70%]
tests/test_kayak_placements.py::test_validate_keeps_the_multiple_airlines_label_the_page_prints PASSED [ 80%]
tests/test_kayak_placements.py::test_validate_keeps_the_first_carrier_of_a_comma_joined_label PASSED [ 90%]
tests/test_kayak_placements.py::test_validate_keeps_airline_differing_only_in_case_from_the_page PASSED [100%]

10 passed in 0.15s
```

`pytest tests/ -v -k "not slow"`:

```
386 passed, 3 deselected in 26.92s
```

Full suite green, no test weakened. (376 before plan 020, +10 new tests in
this file = 386.)

## Commit

Code change (`backend/sources/kayak.py`) committed as
`[phase-2] Ground the airline component of the flight identity`. The two
fixture adaptations landed separately in `785d169` (by the user, not part
of this phase's own commit).

## Deviations from the plan, with reasoning

None to the plan itself. The `_TRUSTED_AIRLINE_LABELS` special-case for
`"multiple airlines"` is an implementation detail not spelled out
explicitly in task 2.1's general rule ("the extracted carrier must appear
in the rendered page"), but is required to satisfy task 2.3 together with
the Phase 1 end-to-end test (`test_search_does_not_extract_a_placement_price`,
whose fixture returns `airline: "Multiple airlines"` for a row where the
literal page text is `"Arajet, Iberia"`) without weakening either test —
confirmed both are simultaneously satisfiable under this design and no
narrower reading was.

## Test gaps / new tests

None. All behavior is covered by the orchestrator-written tests.

## Follow-ups

None beyond the plan's own "Follow-up, explicitly out of scope" section
and Phase 3's live re-check.

## Confidence

Likely-good. Every test in `test_kayak_placements.py` and the full
existing suite passes; the fixture conflict was surfaced and resolved with
explicit user sign-off rather than guessed. Needs Phase 3's live cycle to
confirm the grounding doesn't drop legitimate rows in practice.
