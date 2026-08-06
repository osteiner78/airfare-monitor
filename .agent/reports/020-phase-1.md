# Plan 020 — Phase 1 report: strip paid placements from the extraction input

## What was built

- `_strip_placements(body_text) -> str` (`backend/sources/kayak.py`, module-level
  pure function): removes each paid-placement block. A block starts at the
  line containing `"This is a paid placement from"` and ends at the next
  `"View Deal"` line, inclusive — the end search starts on the line *after*
  the disclosure line, not on it, because the disclosure line itself always
  ends with its own `"View Deal"` (its price sits inline), so anchoring
  there would strip only that one line and leave the block's other
  standalone price repeats behind. Returns the body unchanged when no
  disclosure line is present.
- Wired into `_results_section` before the existing trim (task 1.2), so the
  trim window and `_RESULT_MARKERS` counting both operate on advert-free
  text.
- Wired into `_search_inner`'s call to `self._extract(...)` directly at the
  call site (`_strip_placements(body_text)` passed as the argument), not
  only inside `_results_section`. This was necessary for
  `test_search_does_not_extract_a_placement_price` to be satisfiable at
  all: that test replaces `_extract` with a mock via `patch.object`, which
  bypasses `_extract`'s own internal call to `_results_section` entirely,
  so stripping has to happen before the call reaches `_extract`, not only
  inside it. Grounding (`_validate`) continues to run against the original,
  unstripped `body_text` per task 1.4 — only the extraction call argument is
  stripped.

## Deviation from the plan, with reasoning

Task 1.2 names `_results_section` as the integration point. I kept that
(it's needed for any future direct caller of `_extract`/`_results_section`),
but *also* strip at the `_search_inner` call site. This is a small
addition beyond the plan's literal instruction, made necessary by how the
orchestrator's own end-to-end test mocks `_extract` — without it,
`test_search_does_not_extract_a_placement_price` cannot pass regardless of
what `_results_section` does internally, since the mock never executes it.
The two strip calls are idempotent in the real flow (the second is a
no-op once the first has already removed the marker text).

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
tests/test_kayak_placements.py::test_validate_drops_row_whose_airline_is_absent_from_rendered_text FAILED [ 70%]
tests/test_kayak_placements.py::test_validate_keeps_the_multiple_airlines_label_the_page_prints PASSED [ 80%]
tests/test_kayak_placements.py::test_validate_keeps_the_first_carrier_of_a_comma_joined_label PASSED [ 90%]
tests/test_kayak_placements.py::test_validate_keeps_airline_differing_only_in_case_from_the_page PASSED [100%]

1 failed, 9 passed in 0.16s
```

The one failure (`test_validate_drops_row_whose_airline_is_absent_from_rendered_text`)
is a Phase 2 test (airline grounding), expected to fail until Phase 2 lands
— `_airline_grounded` does not exist yet. All 6 Phase 1 tests pass.

`pytest tests/ -v -k "not slow"`:

```
1 failed, 385 passed, 3 deselected in 26.87s
```

Same single expected Phase 2 failure; no other test affected. (Baseline
before this phase, per CLAUDE.md: 376 passed — the delta is the 10 new
tests in this file, 9 of which are now green.)

## Commit

See `[phase-1.1]` / `[phase-1.2]` commit(s) in `git log` for this phase.

## Test gaps / new tests

None. All behavior is covered by the orchestrator-written tests; no
discovery gaps found.

## Follow-ups

None beyond what the plan already defers (Phase 3 live re-check, and the
plan's own "Follow-up, explicitly out of scope" section).

## Confidence

Likely-good. The stripping logic is validated against the real captured
line shapes from `data/kayak-samples/20260806T012940.952907.txt` (lines
112-137) reproduced verbatim in the test fixture, and against a synthetic
second placement type (car rental) to confirm the loop handles multiple
blocks. Needs Phase 3's live cycle to confirm no placement format was
missed that this test corpus doesn't cover.
