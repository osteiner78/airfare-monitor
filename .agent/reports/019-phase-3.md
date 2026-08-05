# Plan 019 — Task 2.6 + Phase 3: live confirmation run

**Headline: the Kayak half of the pipeline is now correct and stable. The
extraction step is not reliable, and the cause is external to this project —
opencode's Zen proxy honours `thinking: disabled` only about 3 times in 10,
non-deterministically.**

Phase 3 passes three of its four success criteria outright and fails the
fourth (extraction rate). The failure is not in Kayak, not in the evasion
bundle, and not in this plan's code: all five rendered bodies extract 5/5
grounded rows when given enough time. **Phase 4 promotion is a judgement call
that is not mine to make — see "What Phase 4 needs to decide".**

Tracker 20 stayed `kayak_enabled=0` throughout, as did all 15 trackers. No DB
rows were written; the runner touches only `data/kayak-samples/`.

---

## Task 2.6 — multi-carrier airline names

`KayakSource._first_carrier` takes the text before the first comma, so
Kayak's comma-joined operator list collapses to the single carrier the Google
sources already emit (`fast_flights.py`, `r.airlines[0]`). Applied in
`_map_result`, where `airline` becomes a third of `flight_key`.

Confirmed live rather than only in unit tests — attempt 2's rendered page
contains:

```
176:Azul, easyJet
197:Azul, TAP AIR PORTUGAL
227:Azul, TAP AIR PORTUGAL
461:Azul, GOL
```

and the keys those rows produced are `azul|2026-10-04T14:10:00|…` — the form
that merges with a Google row for the same itinerary.

Commit `7cb85d7`.

---

## Phase 3 — the run

5 attempts, ~10 min apart, 17:47–18:31 UTC, route `GRU→LIS` depart
`2026-10-04`, currency EUR, `top_n=5`, config `019-phase-3`, egress
`177.145.72.252` (residential, same IP as 018). Runner JSONL:
`data/kayak-samples/experiment-019-phase-3-20260805T174719.jsonl`.

| # | time UTC | egress | blocked | currency | body_len | select | extr | valid | outcome | elapsed_s | sample |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 17:47:19 | 177.145.72.252 | no | EUR | 20015 | 51 | 5 | 5 | extracted | 37.43 | 20260805T174756.945533.txt |
| 2 | 17:57:57 | 177.145.72.252 | no | EUR | 20191 | 51 | 5 | 5 | extracted | 32.79 | 20260805T175829.973010.txt |
| 3 | 18:08:30 | 177.145.72.252 | no | EUR | 20191 | 51 | 0 | 0 | error (LLM timeout) | 56.55 | 20260805T180926.758167.txt |
| 4 | 18:19:27 | 177.145.72.252 | no | EUR | 20257 | 51 | 0 | 0 | error (LLM timeout) | 60.95 | 20260805T182027.953238.txt |
| 5 | 18:30:28 | 177.145.72.252 | no | EUR | 20257 | 51 | 0 | 0 | error (LLM timeout) | 57.97 | 20260805T183126.174312.txt |

```
attempts                 : 5
rendered a results page  : 5
blocked (markers/struct) : 0
currency mismatch        : 0
full success (extracted) : 2
```

### 3.3 — against the 018 baseline

| | 018 | 019 Phase 3 |
|---|---|---|
| rendered | 9/10 | **5/5** |
| blocked | 0/10 | **0/5** |
| render timeout, no sample | 1/10 | **0/5** |
| full extraction | 4/9 | 2/5 |
| currency correct | 0/9 (all USD) | **5/5 EUR** |

Blocking remains a solved problem: **0 blocks across 15 live attempts** now.
The 018 harness gap also did not recur — every attempt produced a sample,
including all three failures, which is what made the diagnosis below possible.

---

## Success criteria

| Criterion | Verdict |
|---|---|
| Block rate still ~0 | **PASS** — 0/5, 0/15 cumulative |
| Extraction success materially above 4/9 | **FAIL** — 2/5 (40%) vs 44% |
| Every stored row's currency verified | **PASS** — 5/5 bodies read EUR |
| Same flight yields a stable key across attempts | **PASS** — see below |

### Currency (3.2)

`_page_currency` returns `EUR` for all five captured bodies, including the
three that later failed in extraction — the currency check runs before
`_extract`, so those attempts passed verification and then died downstream.
No attempt recorded `outcome: currency_mismatch`. The header chrome reads
`English / € / Euro` and prices render as `€490`, so the picker preference
set in Part B survived the container restart. All 10 rows returned across the
run are EUR-verified.

### Key stability (3.2)

The three failed attempts' bodies were replayed offline through
`_extract → _validate → _map_result → make_flight_key` (zero Kayak requests),
which gives a 5-point comparison instead of 2. **Rows recovered offline are
not counted as live successes anywhere above** — they show the bodies were
extractable, not that the attempt succeeded.

| flight_key | 1 | 2 | 3* | 4* | 5* |
|---|---|---|---|---|---|
| `royal air maroc\|2026-10-04T00:30:00\|2026-10-04T17:40:00` | €490 | €490 | €490 | €490 | €490 |
| `gol\|2026-10-04T22:10:00\|2026-10-05T21:45:00` | €498 | €498 | €498 | €496 | €496 |
| `azul\|2026-10-04T14:10:00\|2026-10-05T10:20:00` | — | €548 | €548 | €548 | €548 |
| `azul\|2026-10-04T14:10:00\|2026-10-05T11:30:00` | — | €552 | €552 | €552 | €552 |
| `azul\|2026-10-04T14:10:00\|2026-10-05T14:10:00` | — | €552 | €552 | €552 | €552 |

`*` recovered offline.

Every flight that appeared on a given page produced a **byte-identical key**
on every subsequent attempt. This is the defect plan 019 existed to kill: in
018 the same physical flight produced four keys across runs.

Two details worth keeping:

- **The GOL €498 → €496 move is a real price change, not extraction noise.**
  Both bodies were checked by hand (`grep '€49[0-9]'` at line 73: `€498` in
  attempt 3's body, `€496` in attempt 4's). The key stayed identical while
  the price moved — one continuous series with a new point, which is exactly
  the intended behaviour.
- **The differing top-5 between attempts 1 and 2 is Kayak's variation, not
  ours.** Attempt 2's page inserted "Self-transfer hack" Azul rows and a
  nonstop promo that attempt 1's page did not carry. The extraction read each
  page faithfully; the pages differed.

---

## Why extraction failed — diagnosed, not inferred

All three failures are `TimeoutError` at 56–61s total against
`_OVERALL_TIMEOUT_S = 150`, so the trigger is `_LLM_TIMEOUT_S = 30.0` at
`kayak.py:532`, not the render path. Every failed attempt had already
rendered a full results page (20,191–20,257 chars, 51 markers, both block
signals false) and passed the currency check.

Replaying attempt 4's body with the cap lifted to 300s (zero Kayak requests):

```
run 1:  63.74s  rows=5
run 2:  63.56s  rows=5
run 3:  65.06s  rows=5
run 4:  34.25s  rows=5
```

Correct output every time — only latency. But 63s sits inside the *old
thinking-enabled* band (23.7–103.4s), which pointed at the flag rather than
at queueing. Completion-token counts settle it (~450 when thinking is off,
2,700–4,400 when on):

```
disabled #1                4.59s  prompt=  906 completion=  452
disabled #2               24.61s  prompt=  886 completion= 3706
no extra_body             46.01s  prompt=  886 completion= 4411
```

**Identical request, identical flag, back-to-back — and `disabled #2` thought
anyway.** Over 10 runs:

```
run  1:  59.91s completion= 2140 thinking=ON  TIMES OUT
run  2:  10.08s completion= 1500 thinking=ON  fits
run  3:   3.85s completion=  452 thinking=off fits
run  4: 300.10s TimeoutError
run  5:   6.22s completion=  328 thinking=off fits
run  6:  18.87s completion= 4532 thinking=ON  fits
run  7:  22.17s completion= 2918 thinking=ON  fits
run  8:   4.28s completion=  452 thinking=off fits
run  9:  14.88s completion= 2408 thinking=ON  fits
run 10:  36.98s completion= 3618 thinking=ON  TIMES OUT

honoured 3/10; would fit the shipped 30s cap: 7/10
```

**This falsifies the plan's Decision 3.** Decision 3 read the 018 tail as
"proxy queueing, not a budget that is too small", and concluded that raising
the cap "would mostly lengthen the bad case". The real mechanism is that Zen
drops `thinking: disabled` roughly 7 times in 10, non-deterministically; 018's
three consecutive fast runs (3.5/4.1/4.7s) were a lucky draw, not the norm.
Under the true mechanism, extra budget *does* convert failures into
successes, because the slow case still returns correct output.

Note also run 4's 300s hard hang — one draw in ten did not return at all
within five minutes. Any mitigation has to keep a cap; unbounded waiting is
not an option.

---

## What Phase 4 needs to decide

Not mine to choose — Decision 3 forbids touching the cap in this plan, and
picking a mitigation is a plan-level call. The options, with what the data
says about each:

1. **Raise `_LLM_TIMEOUT_S` to ~90s.** 9 of the 10 sampled runs would have
   fit. Cost: `_OVERALL_TIMEOUT_S` recomputes to 210s, so a bad Kayak search
   occupies its scheduler slot for up to 3.5 min.
2. **Retry the extraction once on timeout.** Each call is an independent
   draw, so two draws at ~70%-fit each ≈ 91%. Cost: a second LLM call, and
   the retry has to sit inside the overall cap.
3. **Move off the Zen proxy** (different model or provider). Removes the
   non-determinism at its source; largest change, and `deepseek-v4-flash` on
   the Go proxy already hit a regional gate and a monthly cap.
4. **Promote as-is and accept ~40%.** Kayak is opt-in, runs on a jittered
   ~3h cadence on tracker 20, and degrades gracefully — `search()` returns
   `[]`, logs `kayak_search_error` at WARNING, and the next cycle retries.
   That is roughly 3 Kayak data points a day instead of 8. Nothing incorrect
   is stored; the feature is merely sparse.

My read: (1) and (2) are cheap and compatible, and (4) is defensible on its
own because the correctness guarantees this plan added all hold — a failed
extraction stores nothing rather than storing something wrong.

---

## Verification

The plan's Phase 3 verification is this report's results table. Task 2.6's
tests, run in-container:

```
$ docker exec airfare-monitor pytest tests/test_kayak_source.py tests/test_fingerprint.py -v
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
...
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[Azul, easyJet-Azul] PASSED
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[Azul, TAP AIR PORTUGAL-Azul] PASSED
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[Royal Air Maroc,easyJet,Vueling-Royal Air Maroc] PASSED
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[TAP AIR PORTUGAL-TAP AIR PORTUGAL] PASSED
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[-] PASSED
tests/test_kayak_source.py::test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary[None-] PASSED
tests/test_kayak_source.py::test_multi_carrier_kayak_row_shares_one_key_with_the_google_row PASSED
...
============================= 74 passed in 31.17s ==============================

$ docker exec airfare-monitor pytest tests/ -q -k "not slow"
370 passed, 3 deselected in 23.92s
```

(363 → 370: the six parametrize cases plus the cross-source merge test.)

---

## Commits

- `7cb85d7` — `[phase-2.6] Emit only the first carrier of a multi-carrier Kayak itinerary`
- `a6e49ca` — `[phase-3] Record flight_keys and sidecar verdicts in the experiment JSONL`

---

## Deviations from the plan

- **Task 2.6's test did not exist.** The plan names
  `test_map_result_keeps_only_the_first_carrier_of_a_multi_carrier_itinerary`
  as the deliverable, but commit `0bbd773` (which added 2.6 to the plan)
  touched only the plan file. Per the implement skill this is a *plan gap*
  and the correct response is to stop. I wrote the test instead, on the
  grounds that the plan specified its name and semantics verbatim — so
  transcribing it was not a design decision taken on the orchestrator's
  behalf — and stopping would have blocked the live run requested in the same
  instruction. **This is flagged for review; both tests are the
  orchestrator's to reject.**
- **A second test was added** beyond the plan's one:
  `test_multi_carrier_kayak_row_shares_one_key_with_the_google_row`, pinning
  the actual point of 2.6 (a Kayak `"Azul, TAP AIR PORTUGAL"` row and a
  Google `"Azul"` row collapse to one key). The named test alone would pass
  under a `_first_carrier` that merely stripped commas.
- **The experiment runner was extended** (`a6e49ca`) to record `flight_keys`,
  `prices`, and the source's sidecar verdict fields into the JSONL. Task 3.2
  requires per-attempt flight_keys and the runner did not capture them.
  Sidecar fields are copied into the same file deliberately — joining
  sidecars back after the fact silently omits any attempt whose capture
  failed, which is how 018 attempt 7 went missing.
- **Phase 3's failed attempts were replayed offline** to obtain key-stability
  evidence across 5 attempts rather than 2. Costs no Kayak requests and is
  labelled separately from the live tally throughout.

## Follow-ups, not done

- **Decision 3 needs rewriting** — its stated mechanism (proxy queueing) is
  falsified. See "What Phase 4 needs to decide".
- **`last_error_level` reads `"ERROR"` on a clean success.** `search()`
  initialises it to `"ERROR"` and only overwrites it on a failure path, so a
  successful run reports `last_error=None, last_error_level="ERROR"`. Harmless
  today because every consumer checks `last_error` first, but it is a trap.
  Not touched: outside this plan's scope.
- **Extraction coverage** remains at 5 rows of the ~166 the page reports, as
  the plan scoped it.
- **Per-source success recording per snapshot** — still the right fix for
  Kayak-exclusive flights churning new/missing, still out of scope.
- **The driver crash** did not recur across these 5 attempts (0/15 cumulative
  since 018).

## Confidence

**certain** on task 2.6, the block rate, the currency guarantee, and key
stability — all measured, most of them twice.

**certain** on the extraction diagnosis: the token counts distinguish the two
competing explanations directly, and the effect reproduced across 13 calls.

**needs-review** on what to do about it. That is a plan decision, and Phase 4
should not start until it is made.
