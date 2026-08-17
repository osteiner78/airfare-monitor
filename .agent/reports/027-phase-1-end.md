# 027 Phase 1 — make the benchmark measure what production measures

**Date:** 2026-08-17
**Plan:** `.agent/plans/027-refactor-scan-remediation.md`, Phase 1 (#4)

## What I built

1. Extracted `_build_extraction_user_message(body_text, top_n, depart_date)`
   as a module-level pure function in `backend/sources/kayak.py`, placed
   right after `_results_section` (which it calls). `_extract` now calls it
   instead of building the message inline.
2. `scripts/kayak_model_benchmark.py` imports `_build_extraction_user_message`
   from `backend.sources.kayak` and deleted its byte-copy (`_user_message`);
   the one call site in `_call()` was updated to use the imported name. The
   now-unused `_results_section` import was replaced by the new import.
3. `scripts/kayak_model_benchmark.py`'s local `_time_grounded` (which scored
   an unparseable timestamp as ungrounded and had no 24-hour-page fallback —
   both diverging from production) was deleted and replaced with
   `_time_grounded = KayakSource._time_grounded`, an object-identity alias.
   `_keys_time_grounded`'s body is unchanged — it already called `_time_grounded`
   per key part, so no caller-side changes were needed.

## Tests added (both are plan gaps I filled, not pre-written by an orchestrator)

The plan describes what these tests should assert but the repo had no test
file for `scripts/kayak_model_benchmark.py` at all, and no existing test
pinned `_extract`'s inline prompt string. Per this project's established
pattern (every other phase note in CLAUDE.md ends "pinned by tests/test_X.py"
added during that phase's own implementation, not supplied in advance), I
wrote them as part of this phase rather than stopping:

- `tests/test_kayak_source.py::test_build_extraction_user_message_is_pinned`
  — characterization test pinning `_build_extraction_user_message`'s exact
  output for a known input.
- `tests/test_kayak_model_benchmark.py` (new file):
  - `test_benchmark_grounding_function_is_productions` — asserts
    `bench._time_grounded is KayakSource._time_grounded` (object identity,
    not just equal behavior), so the copy cannot silently return.
  - `test_benchmark_grounding_keeps_an_unparseable_time` — the axis the
    drifted copy got wrong in the strict direction.
  - `test_benchmark_grounding_falls_back_to_24_hour_form` — the axis the
    drifted copy had no fallback for at all.

## Verification

Full suite, run inside the container (`airfare-monitor`, which already has
`requirements-dev.txt` installed — Active dev mode):

```
$ docker exec airfare-monitor python -m pytest tests/ -v -k "not slow"
...
====================== 517 passed, 3 deselected in 39.18s ======================
```

(517 vs. the 509 previously recorded in CLAUDE.md: +4 from this phase's new
tests, +4 from an already-uncommitted `test_airline_identity.py` present at
session start — unrelated to this phase.)

Plan-specified `summarize` re-scoring check, against a real historical JSONL,
confirming the shared grounding function runs end-to-end without error:

```
$ docker exec airfare-monitor python scripts/kayak_model_benchmark.py summarize \
    --jsonl data/kayak-samples/model-benchmark-20260805T192933.jsonl
| model | runs | correct | p50 s | p90 s | max s | fits 30s | completion tok p50/max | key determinism |
|---|---|---|---|---|---|---|---|---|
| `deepseek-v4-flash-free` | 50 | 49/50 | 11.6 | 33.9 | 74.1 | 43/50 | 2248/6965 | 98% |
| `mimo-v2.5-free` | 50 | 49/50 | 7.0 | 20.0 | 58.7 | 47/50 | 523/523 | 98% |
| `laguna-s-2.1-free` | 50 | 27/50 | 32.1 | 80.7 | 120.1 | 9/50 | 852/6432 | 45% |
| `longcat-2.0-free` | 50 | 39/50 | 10.2 | 11.6 | 13.1 | 39/50 | 478/538 | 78% |
```

## Deviations from the plan

None in substance. The plan's task list didn't name test file paths (unlike
most prior phases in this repo, which had pre-existing pinned tests); see
"Tests added" above for how that gap was resolved.

## Follow-ups / noted, not done

- Phase 1 does not re-run the live model selection with the corrected
  benchmark. The plan doesn't ask for that here (Phase 0's gate on a clean
  4-tracker Kayak cycle is a separate, already-passed precondition per the
  plan header) — flagging in case a re-verification of `mimo-v2.5` under the
  now-correct scoring rule is wanted later.
- CLAUDE.md's `KayakSource` bullet (long paragraph about `_LLM_MODEL`
  selection) still describes the benchmark's `_time_grounded` as "the check
  that caught it" in the past tense of plan 019 — left as-is since it's
  historically accurate; the `scripts/kayak_model_benchmark.py` bullet now
  notes the drift and the fix.

## Confidence

**certain** — small, mechanical extraction; full suite green; both plan
verification commands ran and produced the expected shape of output.

## Commit

See `git log` for `[phase-1.1]`-tagged commit following this report.
