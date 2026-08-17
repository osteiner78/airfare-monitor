# 027 — Acting on the refactor scan (026)

**Input:** `.agent/reports/026-refactor-scan-all-codebase.md`
**Date:** 2026-08-15
**Orchestrator verdict:** the scan is well-calibrated. 4 of 15 findings are
"do now", the rest carry triggers, and its three "do not refactor" calls are
right. I verified all four ✅ findings against the source before accepting
them; all four hold. One reordering and two additions below.

---

## Where I agree

**#1, #4, #6, #7 are all real and all worth doing.** Verified:

- **#1** — the three strip functions are genuinely one algorithm. All three
  share the identical skeleton (`end = i + 1`; `limit = min(len(lines), i + 1 +
  MAX)`; scan while `end < limit` and the end-condition is unmet; then
  `i = end + 1` if a terminator was found, else drop *only* the start line).
  They differ solely in start predicate, end predicate and bound. The
  "end-search starts on the line after the start line" subtlety that plan 020's
  docstring emphasises is common to all three, so a generic preserves it.
- **#4** — confirmed, and **worse than the report states**.
- **#6** — `search_and_store(tracker_id, delay: bool = True)` (scheduler.py:63)
  plus two near-identical `getattr(source, "last_error", …) → insert_log`
  blocks at 95–103 and 130–140.
- **#7** — scheduler.py:152–168 hand-spells 12 of `FlightResult`'s fields.

## Where I disagree

**The Top 3 ordering is wrong. #4 should be first, not second.** The report
ranks it on size ("cheapest fix that removes a currently-real drift"). The
stronger argument is that this drift **has already influenced a production
decision**: `kayak.py`'s own header records that
`scripts/kayak_model_benchmark.py verify` was used on 2026-08-15 to choose the
Go endpoint and confirm `mimo-v2.5`. That selection ran against a scoring rule
that differs from production on two axes, not one:

| input | benchmark `_time_grounded` | production `_time_grounded` |
|---|---|---|
| unparseable timestamp | `False` — scores the row wrong | `True` — deliberately keeps it |
| 24-hour page (no am/pm anywhere) | no fallback — marks **every** row ungrounded | falls back to the 24h forms |

The second is the serious one: replay a pt-BR/de-CH force-redirect body and the
benchmark scores a perfectly good model at zero. This is a measuring instrument
that reads differently from the thing it measures, in the one script whose
entire job is picking production models. That outranks a field-drop trap that
has not fired yet.

**#1 carries a risk the report undersells.** These three functions are guards
earned by three separate production incidents, and their docstrings carry the
evidence (the €806 phantom, the VCP/ORY nearby-airport promos, the €702
self-transfer fare). The generic must take only the *skeleton*; each wrapper
keeps its own docstring and its own early-exit guard. A consolidation that
collapses the three docstrings into one loses the reason each bound exists,
which is most of their value. This is the same reasoning behind the report's
own #15 ("do not consolidate the dedupe sites") — the difference is that here
the *shape* is identical and only the parameters differ, whereas there the
rules genuinely differ.

## What the report buries

Its best observation is the last paragraph and it has no verdict number:
**~500 lines of client-side logic with zero execution-based tests, holding
three documented cross-file invariants** (palette identity, relative-time
bucketing, colour-rank + sticky-missing fallback). Three of the report's own
findings are blocked on it. That is not a refactor — it is a missing safety
net, and it belongs on the roadmap as the opening move of the expandable-row
UI work (which will grow `filters.js` substantially). Recorded in Phase 5, not
built now: a JS harness with no consumer is the speculative work this project's
conventions rule out.

---

## Plan

### Phase 0 — gate: confirm the LLM provider switch (no code)

`kayak.py`'s endpoint changed at 03:22 today after three days of ~95% failure.
One tracker has since succeeded (03:32, 5 rows, clean). **Do not stack refactors
on `kayak.py` until a full cycle across all four Kayak trackers comes back
clean** — otherwise the next failure has two candidate causes.

**Pass condition:** 4 trackers, ~5 rows each, no `RateLimitError` in
`system_logs`.

### Phase 1 — #4: make the benchmark measure what production measures

1. Extract `_build_extraction_user_message(body_text, top_n, depart_date)` as a
   module-level pure function in `kayak.py`; `_extract` calls it.
2. The benchmark imports it, deleting its byte-copy.
3. The benchmark imports `KayakSource._time_grounded`, deleting its drifted
   local copy. Its callers already unpack production-shaped results.

**Tests:** a characterization test pinning the extracted message (the benchmark
is uncovered, so this is the prerequisite the report correctly demands); plus a
test asserting the benchmark's grounding function *is* production's, so the copy
cannot silently return.

**Verify:** full suite + `scripts/kayak_model_benchmark.py summarize` re-scoring
an existing JSONL offline, which is exactly what that mode exists for.

### Phase 2 — #1: one strip-block algorithm

`_strip_blocks(lines, start_pred, end_pred, max_lines) -> list[str]`, pure and
module-level. Each of the three becomes a thin wrapper binding its predicates
and bound, **keeping its docstring and early-exit guard verbatim**.

**Tests:** unchanged — `test_kayak_placements.py`, `test_kayak_offroute_prices.py`
and `test_kayak_source.py` pin the behaviour and must stay green untouched. That
is the whole proof.

### Phase 3 — #7 + #6: scheduler hygiene (one file, one test run)

1. `prices` list becomes `{**asdict(r), "flight_key": make_flight_key(r)}`.
   `insert_flight_prices` reads columns with `p.get(...)`, so extra keys are
   ignored and the mapping stays total by construction.
2. Remove `delay`'s default; the APScheduler registration passes it explicitly.
3. Extract `_log_source_error(event, source, tracker_id)` for the two duplicated
   observability blocks.

**Tests:** a test asserting every `FlightResult` field reaches the row dict —
that is the trap #7 describes, and it is what makes Passengers' new fields safe.

### Phase 4 — record the deferred items

Add to `TODO.md`, each with the trigger the report assigned:
`_build_detail_context` extraction (#2) and the `browser_render` split (#3) as
the opening moves of the expandable-row and Skyscanner phases respectively;
`SearchOutcome` (#9) as part of Skyscanner, since a new source is when the
convention must be re-learned; `db.py`'s `_connect()` (#10) bundled into the
DB-size normalisation work; the JS test harness as the opening move of the
expandable-row UI.

`tracker_sources` (#12) is already on the roadmap — no action.

---

## Explicitly not doing

- **#15, `fingerprint.py`, and the timeout constants** — the report's three
  "do not touch" calls, all correct. `fingerprint.py` landed two days ago with
  a verified key-preserving migration; the timeout constants are pinned by a
  test that reads source text.
- **#11, #13** — the report marks both ❌ and it is right; an 8-line duplication
  and a documented default are not worth cross-module churn.
- **#5, #14** — cheap but unprotected (JS side), near-zero churn. They become
  worth doing once a JS harness exists, not before.
