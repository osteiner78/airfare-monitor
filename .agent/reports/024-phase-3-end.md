# 024 Phase 3 — make the worker budget count its real waits

**Date:** 2026-08-13
**Plan:** `.agent/plans/024-code-review-remediation.md`, Phase 3 (finding N1/A2)

---

## What was built

**1. `_WORKER_TIMEOUT_FACTOR` replaced by an explicit sum (`backend/sources/kayak.py`).**
The 2.5x factor was written from a two-wait premise (main `page.goto` +
`_wait_for_results_stable`) while the child actually performs four sequential
waits — warmup `page.goto`, warmup dwell, main `page.goto`, stable-wait — i.e.
140s of waiting its own code permits against a 112.5s kill cap. The budget is
now stated rather than implied:

```python
_WARMUP_TIMEOUT_S = 20.0
_MAX_WARMUP_DWELL_S = 5.0
_WORKER_STARTUP_ALLOWANCE_S = 15.0
_WORKER_TIMEOUT_S = (
    _WARMUP_TIMEOUT_S + _MAX_WARMUP_DWELL_S + 2 * _RENDER_TIMEOUT_S
    + _WORKER_STARTUP_ALLOWANCE_S
)                                   # 130.0
_OVERALL_TIMEOUT_S = _WORKER_TIMEOUT_S + _LLM_TIMEOUT_S + 30.0   # 220.0
```

`_render`'s `timeout = _WORKER_TIMEOUT_FACTOR * _RENDER_TIMEOUT_S` became
`timeout = _WORKER_TIMEOUT_S`. Measured at runtime: child worst case 115s
(20 + 5 + 45 + 45) against a 130s cap; overall 220s with 30.0s of slack.

**2. The warmup goto uses its own cap (`backend/sources/kayak_render.py:96`).**
`timeout=_RENDER_TIMEOUT_S * 1000` → `timeout=_WARMUP_TIMEOUT_S * 1000`. The
warmup loads the homepage, not a results page, so it had no reason to hold the
full 45s render budget — and the plan's arithmetic budgets it 20s.

**3. `_MAX_WARMUP_DWELL_S` is tied to the config it bounds.**
`KayakRenderConfig.warmup_dwell_s` default is now `(2.0, _MAX_WARMUP_DWELL_S)`
instead of the literal `(2.0, 5.0)`. Small deviation from the plan's literal
text, taken because a budget line whose comment reads "upper bound of
`KayakRenderConfig.warmup_dwell_s`" is exactly the kind of hand-maintained
premise this phase exists to eliminate. Pinned by a new test (see below).

**4. `tests/test_kayak_timeout_budget.py` rewritten as the plan directs.**
`test_the_worker_cap_covers_both_render_waits` — whose name and arithmetic were
both wrong — is replaced by
`test_the_worker_cap_covers_every_wait_the_child_performs`, which **reads the
waits out of `kayak_render.py`'s own source** rather than listing them by hand
(`timeout=X * 1000` and `cap_seconds: float = X` are the only two shapes the
worker uses to bound a wait). It asserts both that the enumerated count is
still 3 and that `_WORKER_TIMEOUT_S` clears their sum plus the dwell.

---

## Verification

### The rewritten test fails before the implementation (fail-first)

```
$ docker exec airfare-monitor python -m pytest tests/test_kayak_timeout_budget.py -v
...
E       AttributeError: module 'backend.sources.kayak' has no attribute '_MAX_WARMUP_DWELL_S'
FAILED tests/test_kayak_timeout_budget.py::test_overall_timeout_exceeds_worst_case_render_plus_llm
FAILED tests/test_kayak_timeout_budget.py::test_the_slack_is_a_real_margin_not_a_rounding_error
FAILED tests/test_kayak_timeout_budget.py::test_the_budget_is_derived_not_hardcoded
FAILED tests/test_kayak_timeout_budget.py::test_the_worker_cap_covers_every_wait_the_child_performs
FAILED tests/test_kayak_timeout_budget.py::test_the_warmup_dwell_bound_matches_the_config_it_claims_to_bound
============================== 5 failed in 0.13s ===============================
```

### After the implementation

```
$ docker exec airfare-monitor python -m pytest tests/test_kayak_timeout_budget.py -v
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /app
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.2
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests/test_kayak_timeout_budget.py::test_overall_timeout_exceeds_worst_case_render_plus_llm PASSED [ 20%]
tests/test_kayak_timeout_budget.py::test_the_slack_is_a_real_margin_not_a_rounding_error PASSED [ 40%]
tests/test_kayak_timeout_budget.py::test_the_budget_is_derived_not_hardcoded PASSED [ 60%]
tests/test_kayak_timeout_budget.py::test_the_worker_cap_covers_every_wait_the_child_performs PASSED [ 80%]
tests/test_kayak_timeout_budget.py::test_the_warmup_dwell_bound_matches_the_config_it_claims_to_bound PASSED [100%]

============================== 5 passed in 0.12s ===============================
```

### Arithmetic, read from the running module

```
$ docker exec airfare-monitor python -c "..."
warmup 20.0 dwell 5.0 render 45.0 startup 15.0
_WORKER_TIMEOUT_S 130.0
_OVERALL_TIMEOUT_S 220.0
slack 30.0
child worst case 115.0
```

Matches the plan's 130s / 220s, and the `>= 25.0` slack assertion clears at 30.0s.

### "Adding a fourth wait must fail the suite" — checked by actually adding one

A fourth `page.goto(url, timeout=_RENDER_TIMEOUT_S * 1000)` was temporarily
inserted into `kayak_render.render` and the file restored afterwards
(`git diff` confirmed the restore left only this phase's two intended lines):

```
E       AssertionError: the render worker performs 4 capped waits ['_WARMUP_TIMEOUT_S', '_RENDER_TIMEOUT_S', '_RENDER_TIMEOUT_S', '_RENDER_TIMEOUT_S'], not the 3 this budget was sized for -- re-derive _WORKER_TIMEOUT_S before updating this count
E       assert 4 == 3
FAILED tests/test_kayak_timeout_budget.py::test_the_worker_cap_covers_every_wait_the_child_performs
1 failed, 4 passed in 0.08s
```

### Full suite

```
$ docker exec airfare-monitor python -m pytest tests/ -q -k "not slow"
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 44%]
........................................................................ [ 59%]
........................................................................ [ 74%]
........................................................................ [ 89%]
..................................................                       [100%]
482 passed, 3 deselected in 298.93s (0:04:58)
```

(481 before this phase; +1 is
`test_the_warmup_dwell_bound_matches_the_config_it_claims_to_bound`.)

### Live Kayak cycle — render unaffected

`POST /api/trackers/21/search` (GRU-GVA, `kayak_enabled=1`, due since
03:41:35), 2026-08-13 04:35:57Z. Sidecar
`data/kayak-samples/20260813T043647.124617.json`:

```json
{
  "config_id": "c1-c4",
  "blocked_by_markers": false,
  "blocked_by_structure": false,
  "extracted_rows": 0,
  "validated_rows": 0,
  "outcome": "error",
  "elapsed_s": 49.31,
  "body_len": 19722,
  "select_count": 51,
  "captured_at": "2026-08-13T04:36:47.125173+00:00"
}
```

**The render is healthy and unaffected**, which is what Phase 3 touches: a full
19,722-char results page, 51 `Select` markers, neither block signal fired, and
the whole attempt finished in 49.3s against the new 130s worker cap. Because
the warmup goto ran, dwelled and handed off inside that 49.3s, the tightened
20s warmup cap is confirmed to be comfortable in practice, not just on paper.

**`outcome: error` is the LLM step, and it is a pre-existing production
condition unrelated to this phase** — see the finding below.

---

## Finding: Kayak extraction is currently dead on the LLM quota (not caused by this phase)

`system_logs` id 14789:

```
ERROR kayak_search_error tracker 21
KayakSource: RateLimitError: Error code: 429 - {'type': 'error', 'error':
{'type': 'FreeUsageLimitError', 'message': 'Error from provider (Console):
Rate limit exceeded. Please try again later.'}}
```

Every Kayak attempt is failing this way, and has been since well before this
session:

```
2026-08-13 04:36:47 | 21 | 429 FreeUsageLimitError
2026-08-13 04:29:46 | 22 | 429 FreeUsageLimitError
2026-08-13 04:20:46 | 20 | 429 FreeUsageLimitError
2026-08-13 03:16:33 | 21 | 429 FreeUsageLimitError
2026-08-13 03:08:55 | 20 | 429 FreeUsageLimitError
2026-08-13 03:07:44 | 22 | 429 FreeUsageLimitError
2026-08-13 02:03:59 | 20 | 429 FreeUsageLimitError
2026-08-12 23:59:57 | 20 | 429 FreeUsageLimitError
2026-08-12 23:58:58 | 21 | 429 FreeUsageLimitError
2026-08-12 23:54:03 | 22 | 429 FreeUsageLimitError
```

The `mimo-v2.5-free` free tier on opencode.ai Zen is exhausted, so every render
— all of them successful — is thrown away at the extraction step. This is
degrading correctly and loudly (`ERROR` on `/monitor`, snapshot still created
from fli's rows), so nothing is silently wrong, but **no Kayak row has been
stored for some hours and none will be until the quota resets or the model/key
changes.** Out of scope for Phase 3; flagged for a decision. It also means the
plan's live verification could confirm the render half of the cycle but not an
end-to-end extraction — the render half is the half Phase 3 changes.

---

## Commit

`248a5d1` — `[phase-3] Budget the Kayak render worker by its real waits, not a factor`

---

## Deviations from the plan

1. **`warmup_dwell_s` default now references `_MAX_WARMUP_DWELL_S`** rather than
   repeating `5.0`. Reasoning above; it is one token and it makes the budget's
   own comment true by construction.
2. **Three tests beyond the named one were touched, mechanically.** The plan
   authorises rewriting `test_the_worker_cap_covers_both_render_waits` only, but
   deleting `_WORKER_TIMEOUT_FACTOR` breaks every reference to it:
   `_worst_case()` (a helper, not a test) and
   `test_the_budget_is_derived_not_hardcoded`'s recomputed formula. Both were
   adapted to the new constants with their assertions and intent unchanged —
   the same repair pattern used for the plan 019/020 fixture adaptations and
   024 Phase 2's tuple unpacking. No assertion was weakened; the file went from
   4 tests to 5.
3. **No orchestrator-written test existed for this phase.** The plan directs the
   implementer to rewrite an existing test rather than supplying a new failing
   one, so the usual "confirm the deliverable test fails first" step was done
   against the rewritten file instead (output above).

## New tests added

- `test_the_warmup_dwell_bound_matches_the_config_it_claims_to_bound`
  (discovery gap): `_MAX_WARMUP_DWELL_S` is only an honest budget line while it
  really is the upper bound of the dwell `_warmup_sequence` draws. Flagged here
  rather than added quietly.

## Follow-ups / noted but not done

- **The LLM 429 above needs a decision** (wait for reset, paid tier, or a
  different model id). Nothing in plan 024 covers it.
- `.agent/reports/024-phase-1-end.md` is still untracked from the Phase 1
  session; left alone rather than folded into this phase's commit.
- CLAUDE.md's test count (`456`) is still stale at 482 — Phase 6 owns that line,
  per the plan.
- `_WORKER_STARTUP_ALLOWANCE_S = 15.0` is a plan-supplied estimate, not a
  measurement. The 49.3s live attempt gives no reason to doubt it, but it is the
  one term in the sum with no evidence behind it.

## Confidence

**certain** on the arithmetic and the test (constant-vs-constant, plus a
source-derived wait count verified to fail on a fourth wait).
**likely-good** on the live half: the render is confirmed unaffected and the
tightened warmup cap is confirmed comfortable, but the LLM quota blocked an
end-to-end extraction, so the full cycle was not observed green.
