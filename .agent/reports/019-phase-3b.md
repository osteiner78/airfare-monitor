# Plan 019 — Phase 3b: extraction model benchmark (offline)

**Headline: `mimo-v2.5-free` replaces `deepseek-v4-flash-free`, and
`_LLM_TIMEOUT_S` goes 30s → 60s. The choice removes the mechanism rather than
managing it — mimo emitted 509 or 523 completion tokens on all 50 runs, two
values and never a reasoning burst, so Zen's unreliable `thinking: disabled`
has nothing to ignore.**

Zero Kayak requests. Zero DB writes. No tracker touched, no scheduler run, and
the extraction prompt is byte-identical to the shipped one (verified, see
"Prompt parity"). Every input was a body already sitting in
`data/kayak-samples/`.

---

## 3b.1 — Model IDs verified against the live model list

`GET https://opencode.ai/zen/v1/models` returns 61 ids; the seven carrying the
`-free` suffix are the candidate set. The plan's names (Mimo v2.5, Laguna S
2.1, Ling-3.0-flash, LongCat-2.0, Nemotron 3 Ultra, North Mini Code) all
resolve, each with a `-free` suffix that a webpage summary would not have told
us. Every one was then confirmed with a **real extraction call** on a real
captured body before any benchmarking:

| model id | in live list | verify call | latency | completion tok |
|---|---|---|---|---|
| `deepseek-v4-flash-free` (incumbent) | yes | OK | 14.0s | 1461 |
| `mimo-v2.5-free` | yes | OK | 7.3s | 509 |
| `laguna-s-2.1-free` | yes | OK | 9.7s | 370 |
| `longcat-2.0-free` | yes | OK | 9.3s | 464 |
| `nemotron-3-ultra-free` | yes | OK | 57.7s | 2087 |
| `north-mini-code-free` | yes | OK | 151.8s | 6289 |
| `ling-3.0-flash-free` | yes | **excluded** | 400 ×3 | — |

**`ling-3.0-flash-free` is excluded for a specific, probed reason**, not a flaky
call: it rejects `response_format={"type": "json_object"}`. A plain chat
completion to the same id succeeds (`{"ok":true}`); adding JSON mode returns
`400 Upstream request failed: [400] Provider returned error`, three times out
of three. The shipped `_extract` requires JSON mode, so the id is real but
unusable here.

---

## 3b.2 — Replay harness

`scripts/kayak_model_benchmark.py` (new), three modes: `list` (live model
list), `verify` (one real call per id — 3b.1), `bench` (the benchmark), plus
`summarize` for re-scoring an existing JSONL.

Fixed subset: the **five bodies captured by the Phase 3 live run**
(`config_id: 019-phase-3`, 20,015–20,257 chars, 51 result markers each, five
distinct md5s). They are the only EUR-verified captures, i.e. the exact shape
production sees now.

Calls are issued **strictly sequentially**, never concurrently: the quantity
being measured is a latency distribution, and running candidates in parallel
would queue them against each other on the same proxy and confound it. Per-run
records land in `data/kayak-samples/model-benchmark-20260805T192933.jsonl`
(fast arm) and `...-20260805T204435.jsonl` (slow arm).

### Prompt parity

The benchmark's user message is a verbatim copy of `_extract`'s, which is a
divergence risk, so it was checked rather than assumed — `_extract` was run
against a stubbed client and its outgoing messages compared to the harness's:

```
user message identical: True
system prompt identical: True
```

---

## 3b.3 — Results

Fast arm: 4 candidates × 5 bodies × 10 runs = **200 real calls**, 120s hard cap
(deliberately far above the shipped 30s so the tail is measured, not
truncated).

| model | runs | correct | p50 s | p90 s | max s | fits 30s | completion tok p50/max | key determinism |
|---|---|---|---|---|---|---|---|---|
| `mimo-v2.5-free` | 50 | **49/50** | **7.0** | **20.0** | 58.7 | **47/50** | **523/523** | **98%** |
| `deepseek-v4-flash-free` | 50 | 49/50 | 11.6 | 33.9 | 74.1 | 43/50 | 2248/6965 | 98% |
| `longcat-2.0-free` | 50 | 39/50 | 10.2 | 11.6 | **13.1** | 39/50 | 478/538 | 78% |
| `laguna-s-2.1-free` | 50 | 27/50 | 32.1 | 80.7 | 120.1 | 9/50 | 852/6432 | 45% |

`correct` = parsed **and** 5 rows **and** every price grounded in the body
**and** every timestamp canonical **and** every clock time grounded in the body
**and** single-carrier airline. `fits 30s` = correct *and* inside the shipped
cap. `key determinism` = mean share of runs per body landing on the modal
`flight_key` set.

Slow arm: the two candidates whose *verify* call already sat outside any
defensible cap, given 5 bodies × 2 runs at a 180s cap rather than ×10 — 100
further calls would have taken an hour to confirm what the first call said.

| model | runs | correct | p50 s | max s | fits 30s | completion tok p50/max |
|---|---|---|---|---|---|---|
| `nemotron-3-ultra-free` | 10 | 10/10 | 62.1 | 71.0 | **0/10** | 2445/3140 |
| `north-mini-code-free` | 10 | 4/10 | 180.1 | 180.1 | **0/10** | 4986/5569 |

Both are accurate when they answer — nemotron read all 10 replays correctly and
was the only candidate at 100% key determinism — and both are disqualified on
latency alone. Neither produced a single run inside the shipped cap; 6 of
north-mini's 10 runs did not return within 180s. Their token counts show why:
they are reasoning models, and no flag stops them.

### A correctness dimension the plan did not name — and it decided the outcome

3b.3 asks for "canonical timestamps". Canonical is not the same as correct.
Kayak prints the cheapest GRU→LIS itinerary as `12:30 am – 5:40 pm`, and
several candidates read that departure as **12:30**, i.e. 12:30 pm. That value
parses, survives `_canonical_timestamp`, and grounds its price — and produces
`royal air maroc|2026-10-04T12:30:00|...` instead of
`...|2026-10-04T00:30:00|...`: **two flight_keys for one physical flight**,
which is the exact defect plan 019 Phase 2 exists to prevent. The body contains
`12:30 am` seven times and `12:30 pm` zero times, so the misread is
unambiguous.

`_time_grounded` therefore gives clock times the same treatment `_price_grounded`
gives prices: the 12-hour rendering must appear in the rendered text. All 200
runs were re-scored under the same rule (`summarize` recomputes it from the
stored keys — no extra calls).

It changes the ranking outright:

| model | correct before | correct after | am/pm misreads |
|---|---|---|---|
| `mimo-v2.5-free` | 50/50 | 49/50 | 1 |
| `deepseek-v4-flash-free` | 49/50 | 49/50 | 0 |
| `longcat-2.0-free` | 50/50 | **39/50** | **11** |
| `laguna-s-2.1-free` | 39/50 | 27/50 | 12 |

On max latency alone `longcat-2.0-free` wins by a mile — 7.85–13.11s across all
50 runs, the tightest tail measured, and it would have been the choice under
the plan's rule as literally written. It reads the page wrong 22% of the time,
and on three of the five bodies the *wrong* reading was the majority answer. A
model that reliably delivers a wrong identity fast is worse for this pipeline
than one that occasionally times out.

### Why mimo, specifically

- **It has no reasoning mode to hide.** 50 runs produced exactly two distinct
  completion-token counts, 509 and 523 — including the two slowest runs.
  Compare `deepseek-v4-flash-free`: 41 distinct counts spanning 308–6,965.
  Phase 3's diagnosis was that Zen honours `thinking: disabled` ~3 times in 10;
  mimo makes the question moot, which is exactly 3b's stated intent.
- **Its tail is network, not reasoning.** The two runs over 30s (34.8s, 58.7s)
  returned the same 523 tokens as the 4.3s run.
- **Equal accuracy to the incumbent** (49/50) at roughly half the p50 (7.0s vs
  11.6s), and its one failure is a single am/pm misread on body 4 run 5, not a
  structural one.

Its single defect is worth recording: **1 run in 50 (2%) produced the 12:30
misread.** deepseek produced none in 50 (its one imperfect run returned 4 rows
instead of 5). If that 2% matters later, the fix is a prompt change, which this
phase is forbidden to make and which would invalidate the comparison.

---

## 3b.4 — Decision

> *"Prefer the model whose worst observed latency fits inside the current 30s
> cap with every run extracting correctly. If none does, prefer the tightest
> tail and raise the cap to fit it."*

No candidate's worst run fits 30s with every run correct, so the second clause
applies — restricted to the models that *are* correct, since a fast wrong
answer is not a candidate. Among those, mimo has the tighter tail (58.7s vs
74.1s) and the tighter body (48/50 under 23s vs deepseek's 44/50).

**`_LLM_MODEL = "mimo-v2.5-free"`, `_LLM_TIMEOUT_S = 60.0`.**
`_OVERALL_TIMEOUT_S` recomputes itself from those (2 × 45 + 60 + 30 = 180s), so
a worst-case Kayak search now occupies its scheduler slot for 3 minutes rather
than 2.5. Kayak is opt-in and runs on a jittered ~3h cadence, and APScheduler's
`max_instances=1`/`coalesce=True` defaults prevent stacking.

The margin is thin and should be stated plainly: the observed max is 58.7s
against a 60s cap. `extra_body={"thinking": {"type": "disabled"}}` stays in
place — it costs nothing and covers the case where the model gains a reasoning
mode later.

**3b.5** — the hard cap stays. Nothing here justifies an unbounded call; the
300s hang seen in Phase 3 is exactly what the cap exists for, and anything past
60s is a lost data point by design (the search returns `[]`, logs at WARNING,
and the next cycle retries).

---

## Verification

Phase 3b's verification is this report's results table. The code change was
also put through the suite:

```
$ docker exec airfare-monitor pytest tests/test_kayak_source.py -q
...........................................................              [100%]
59 passed in 37.82s

$ docker exec airfare-monitor pytest tests/ -q -k "not slow"
........................................................................ [ 77%]
........................................................................ [ 97%]
..........                                                               [100%]
370 passed, 3 deselected in 25.45s
```

`test_extract_disables_model_thinking` still passes — the flag was kept.

---

## Not done, deliberately

**The live re-run.** The plan's Phase 3b verification ends with "re-run Phase
3's confirmation (3–5 live attempts) to confirm the extraction rate actually
moves — the benchmark measures the LLM in isolation, not the pipeline." The
instruction for this session scoped it to the offline benchmark ("costs zero
Kayak requests ... don't touch the extraction prompt or any live tracker"), so
the live confirmation was not run. **Phase 3b is not closed until it is.**
The command, unchanged from Phase 3:

```bash
docker exec airfare-monitor python scripts/kayak_experiment.py \
    --attempts 5 --spacing-minutes 10 --origin GRU --dest LIS \
    --date 2026-10-04 --config-id 019-phase-3b
```

Expected from the benchmark: ~47/50 → roughly 5/5 extractions where Phase 3 got
2/5. If the live rate does not move, the difference is in the pipeline, not the
model.

---

## Deviations from the plan

- **No orchestrator tests exist for Phase 3b**, and none are named in it — the
  phase's declared deliverables are a script and a results table, and its
  Verification section is the table. Flagged rather than filled in: I did not
  write unit tests for the benchmark script. The regression risk sits in
  `kayak.py`, and the existing 59 kayak tests cover it.
- **`_time_grounded` is a correctness metric the plan did not ask for**
  (a discovery gap, per the implement skill). It is measurement code in the
  benchmark script only — no production behaviour changed — but it inverted the
  model ranking, so calling it out matters more than usual.
- **The two slow candidates got a reduced arm** (5 bodies × 2 runs instead of
  ×10). Their verify calls landed at 57.7s and 151.8s, i.e. outside any
  defensible cap before benchmarking started; 100 further calls would have
  taken about an hour to confirm a conclusion the first call already made. Even
  the reduced arm took 36 minutes for 20 calls.
- **Total: 227 real LLM calls** (7 verify + 200 fast arm + 20 slow arm), all
  offline replays. Wall clock 19:29–21:22 UTC.
- **`ling-3.0-flash-free` was never benchmarked** — see 3b.1.

## Follow-ups, not done

- **The live confirmation run** (above) — the one thing that closes this phase.
- **mimo's 2% am/pm misread.** A prompt change is the obvious fix and is out of
  scope here by construction ("changing it mid-benchmark makes the models
  incomparable").
- **`_time_grounded` is not in the production `_validate`.** Extending
  validation to reject ungrounded clock times would kill the misread class
  entirely for every model, at the cost of dropping rows. Worth considering; it
  is a behaviour change to a settled path, so not taken unilaterally.
- Everything still open from Phase 3: per-source success recording, extraction
  coverage (5 of ~166 rows), the driver crash.

## Confidence

**certain** on the measurements — 200 sequential real calls, one JSONL row
each, re-scorable offline from the stored keys.

**likely-good** on the model choice. It follows 3b.4 as written once "tightest
tail" is read as "tightest tail among the correct", which the plan's own
"with every run extracting correctly" clause requires. The 60s cap fits every
observed run with only ~2% headroom, and 50 samples is a thin basis for a tail
estimate.

**needs-review** on whether Phase 3b can be considered complete without the
live re-run. It cannot, in my reading.
