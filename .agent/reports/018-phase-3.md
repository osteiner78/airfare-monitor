# Plan 018 — Phase 3: run the experiment

**Headline: 0 blocks / 10. The C1–C4(+WebGL) bundle gets through PerimeterX.**
Plan 017 Phase 6 was 0/5 successful renders; this run rendered a genuine
results page on 9 of 10 attempts and produced 4 complete end-to-end
extractions. By the plan's own reading (`0–1 blocks / 10 → success`), Step 2
passes and the next stop is Step 5.

**This is a go on the evasion bundle and a no-go on promotion.** Three
data-correctness defects found during the run block Step 5 — see "Blockers
for Step 5". Kayak has been left **disabled** on tracker 20 accordingly.

---

## Step 0 — dropped

No VPN client is installed on `minnie` (`nordvpn`, `openvpn`, `wg` all
absent) and installing one is out of scope. Confirmed with the user, who
amended the plan in `acb0182`: the experiment runs on the residential IP,
which is also the production egress, so Steps 2 and 4 collapse into one.
creepjs's WebRTC probe confirmed egress `177.145.72.252` throughout — the
same IP the plan's decisive manual-browsing evidence came from.

## Step 1 — offline fingerprint smoke test

Clean on every axis the plan's detection ranking names, except one.

```
default UA : Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/149.0.7827.55 Safari/537.36
derived UA : Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.55 Safari/537.36
consistent : True

bot.sannysoft.com:
  WebDriver (New)        : missing (passed)
  WebDriver Advanced     : passed
  Chrome (New)           : present (passed)
  Plugins Length         : 5
  Languages              : en-US
  WebGL Vendor           : Canvas has no webgl context     <-- SELF-OWN
  PHANTOM_*  / HEADCHR_* / SELENIUM_DRIVER / CHR_DEBUG_TOOLS : all ok

navigator probes:
  webdriver           : False
  outerWidth          : 1928        (headless reports 0)
  outerHeight         : 1211
  plugins             : 5
  tz                  : America/Sao_Paulo
  hardwareConcurrency : 6
  webglVendor         : no webgl                            <-- SELF-OWN

creepjs:
  0% headless
  0% stealth
  44% like headless
  WebGL: images/pixels/params/exts/gpu all "blocked"        <-- SELF-OWN
  WebRTC srflx ip: 177.145.72.252
```

### Task 3.1 — expose a WebGL context (fix applied before any live attempt)

The bundle rendered with **no WebGL context at all**. That is a harder
automation tell than the SwiftShader renderer string the plan ranked #3:
every real Chrome has a context and degrades to SwiftShader on a GPU-less
host rather than exposing none. Probed four candidate arg sets:

```
baseline (shipped)             -> {'ok': False, 'vendor': None,  'renderer': None, 'exts': 0}
+enable-unsafe-swiftshader     -> {'ok': True,  'vendor': 'Google Inc. (Google)', 'exts': 35}
+use-angle=swiftshader         -> {'ok': True,  'vendor': 'Google Inc. (Google)', 'exts': 36}
+use-gl=swiftshader            -> {'ok': False, 'vendor': None,  'renderer': None, 'exts': 0}
+angle-swiftshader+unsafe      -> {'ok': True,  'vendor': 'Google Inc. (Google)', 'exts': 36}
```

Shipped `--use-gl=angle --use-angle=swiftshader`; verified on a real https
origin as
`Google Inc. (Google) | ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) | exts=36`.
Pinned by the orchestrator's `test_launch_args_expose_a_webgl_context`.

### Redirect check

**`kayak.com` does force-redirect from this IP** — but only the homepage:

```
requested : https://www.kayak.com/
final URL : https://www.kayak.com.br/?ispredir=true
title     : Pesquise voos, hotéis e aluguel de carros | KAYAK
html lang : pt-br
```

The **deep search URL does not redirect**. Every one of the 9 captured
bodies is in English (`One-way`, `Sao Paulo`, `Lisbon`, `Economy`,
`166 of 721 flights`), so task 1.8's pinned English parsing surface holds
where it matters. Tasks 1.9 (dot-thousands grounding) and 1.10
(`_RESULT_MARKERS` as a set) were not exercised in anger but remain the
correct insurance if Kayak ever redirects the search path too.

## Step 2 — the bundle against Kayak

Route `GRU→LIS`, depart `2026-10-04` (~60 days out), untracked by any
tracker. 10 attempts, ~10 min apart, 05:29–07:11 UTC, config `c1-c4-webgl`.
Tracker 20's Kayak due time was pushed `06:26:48 → 08:00:00` for the window
so its scheduled attempt could not land mid-run (user chose "delay" over
"disable"); restored afterwards, see "State changes".

| # | time UTC | egress | blocked | body_len | select | extr | valid | outcome | elapsed_s | sample |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 05:29:33 | 177.145.72.252 | no | 19949 | 51 | 0 | 0 | error | 71.91 | 20260805T053045.502416.txt |
| 2 | 05:40:45 | 177.145.72.252 | no | 19949 | 51 | 0 | 0 | error | 65.65 | 20260805T054151.395187.txt |
| 3 | 05:51:51 | 177.145.72.252 | no | 19949 | 51 | 0 | 0 | error | 61.25 | 20260805T055252.889150.txt |
| 4 | 06:02:53 | 177.145.72.252 | no | 20349 | 51 | 5 | 5 | extracted | 59.46 | 20260805T060352.529333.txt |
| 5 | 06:13:52 | 177.145.72.252 | no | 20349 | 51 | 5 | 5 | extracted | 61.27 | 20260805T061454.037209.txt |
| 6 | 06:24:54 | 177.145.72.252 | no | 20343 | 51 | 5 | 5 | extracted | 61.92 | 20260805T062556.195997.txt |
| 7 | 06:35:56 | 177.145.72.252 | no sample | - | - | - | - | render timeout | 150.07 | - |
| 8 | 06:48:26 | 177.145.72.252 | no | 20343 | 51 | 0 | 0 | error | 61.38 | 20260805T064928.138169.txt |
| 9 | 06:59:28 | 177.145.72.252 | no | 20343 | 51 | 5 | 5 | extracted | 60.15 | 20260805T070028.517358.txt |
| 10 | 07:10:28 | 177.145.72.252 | no | 19923 | 51 | 0 | 0 | error | 73.28 | 20260805T071142.031360.txt |

```
attempts                 : 10
rendered a results page  : 9
blocked (markers/struct) : 0
render timeout, no sample: 1
full success (extracted) : 4
```

**Attempt 7 is counted as inconclusive, not as a block.** It hit
`_OVERALL_TIMEOUT_S` (150.07s) during `_render` and captured no body, so
there is no evidence either way — a hung connection could be a soft block or
plain network flakiness. Counting it as a block would overstate; counting it
as a pass would understate. Even in the worst case it is 1/10, still inside
the plan's success band.

**The six `outcome: error` rows are not Kayak failures.** Every one of them
rendered a full results page (19,923–20,349 chars, 51 markers, both blocked
signals false) and then failed in the LLM extraction step — see task 3.2.

## Tasks 3.2 / 3.3 — extraction was the real bottleneck

Diagnosed by replaying attempt 1's captured body against the live endpoint,
costing zero Kayak requests.

| Config | prompt tok | completion tok | latency |
|---|---|---|---|
| Full body (19,949 ch) | ~6,000 | — | **103.4s** |
| Trimmed (1,804 ch, 9%) | 929 | 3,590 | 29.6s |
| Trimmed | 929 | 4,311 | 33.8s |
| Trimmed | 830 | 2,677 | 49.4s |
| Trimmed | — | — | 23.7s / 23.8s |
| **Trimmed + thinking disabled** | 850 | **439–453** | **3.5s / 4.1s / 4.7s** |

`_LLM_TIMEOUT_S` is 30.0, so the shipped configuration was timing out on
roughly half of all attempts *after* a successful render.

**3.2 — `_results_section(body_text, max_results)`.** The page is fetched
with `sort=price_a` and the caller only ever wants `top_n` rows, so the first
`top_n` itinerary blocks suffice — ~9% of the body. Block *ends* are exact
(each ends with a `_RESULT_MARKERS` line, so this survives a force-redirect
the same way `_wait_for_results_stable` does); only the first block's start is
estimated, from the widest of the leading blocks. Returns the body unchanged
when no marker is found — trimming is an optimisation, and dropping the page
would waste a real request. Grounding still runs against the **full** body in
`_search_inner`, so trimming cannot cause a false drop.

Trimming removed the page's date context, which dated every row to
`1970-01-01`. `depart_date` is now threaded into `_extract` and stated in the
prompt instead of inferred — restoring `2026-10-04T00:30:00` departures and
correctly rolling overnight arrivals to `2026-10-05`. This was latent at full
body too, where the model had to guess a year from `"Sun 10/4"`.

**3.3 — disable model thinking.** Prompted by the user pointing at
DeepSeek's thinking-mode docs. Thinking is on by default at `"high"` effort,
burning 2,677–4,311 reasoning tokens to emit ~300 tokens of JSON. Reading
fields out of already-structured text is not a reasoning task; disabled it
measures 3.5–4.7s on 439–453 tokens with identical output and 5/5 rows still
grounded. `extra_body={"thinking": {"type": "disabled"}}` is the
OpenAI-compatible form and **is passed through by opencode's Zen proxy**
(verified against live calls).

Combined: **103.4s → under 5s**, so `_LLM_TIMEOUT_S` stays at 30 — the user
explicitly preferred trimming over raising the budget.

End-to-end `search()` against a captured body, post-fix: **4.0s and 3.7s**,
5 `FlightResult`s each, `last_error=None`.

**Caveat: a latency tail remains.** One of six thinking-disabled runs took
32.0s and timed out; the other five were 3.5–4.7s. That looks like proxy
queueing rather than anything about the request. It degrades gracefully
(`search()` returns `[]`, logs, next cycle retries), but the 30s cap is not a
guaranteed fit.

---

## Blockers for Step 5 (promotion) — none fixed, all out of scope for "phase 3 only"

1. **Currency is wrong.** `_build_url` sends `?currency=EUR`, but every
   captured body shows `$ United States dollar` and `$`-prefixed prices.
   `_map_result` stamps the *tracker's* currency onto the row, so promoting
   as-is writes USD values labelled EUR. For GRU→ZRH the USD number is the
   larger one, so `historical_best_price` (a `MIN` that is never recomputed)
   would not be corrupted — but the price series, the chart, and
   `best_source` attribution would all be wrong.
2. **`flight_number` is unstable and mostly absent.** Across runs the same
   Royal Air Maroc flight came back as `""`, `"N/A"`, `"unknown"`, and
   `"AT"`; the Azul/GOL codeshare as `""` and `"AD+G3"`. `make_flight_key` is
   `airline|flight_number|departure_time`, so one physical flight yields four
   distinct keys — silently fragmenting its history into disconnected series
   and breaking sticky top-N and delta computation. Kayak's collapsed results
   list genuinely does not print flight numbers, so this needs a decision
   (drop `flight_number` from Kayak keys, expand each result to read it, or
   accept fragmentation), not a patch.
3. **The extraction latency tail** above.

Because of (1) and (2), **Kayak was left disabled on tracker 20**
(`kayak_enabled = 0`). The plan's Step 5 is itself "re-enable Kayak on
tracker 20", so off-until-Step-5 is the plan-aligned end state; the flag had
been left at 1 by plan 017 Phase 6.

## A harness gap found by attempt 7

`_search_inner` awaits `_render` **before** building the sample record, so a
render that hangs until `_OVERALL_TIMEOUT_S` produces **no sample at all** —
precisely the attempt where a body would be most diagnostic. Task 2.4's "on
every Kayak attempt, persist the rendered body" is not met on that path.
There is no body to persist when the render never returns, but the *attempt*
goes unrecorded in the sidecar set, so any sidecar-driven analysis silently
omits the hardest failures. The Phase 3 results table is therefore driven off
the JSONL and joined to sidecars, not driven off sidecars.

## Verification

Plan's Verification block for Phase 3: "Sample files under
`data/kayak-samples/` plus a results table in `.agent/reports/018-phase-3.md`".
Both present — 9 body/sidecar pairs plus
`experiment-c1-c4-webgl-20260805T052933.jsonl`, and the table above.

### New/changed tests

```
tests/test_kayak_source.py::test_results_section_keeps_only_the_requested_number_of_itineraries PASSED
tests/test_kayak_source.py::test_results_section_keeps_the_first_itinerary_intact PASSED
tests/test_kayak_source.py::test_results_section_drops_page_chrome_around_the_results PASSED
tests/test_kayak_source.py::test_results_section_recognises_localized_action_buttons PASSED
tests/test_kayak_source.py::test_results_section_returns_body_unchanged_when_no_markers_found PASSED
tests/test_kayak_source.py::test_results_section_returns_body_unchanged_for_non_positive_top_n PASSED
tests/test_kayak_source.py::test_results_section_handles_fewer_results_than_requested PASSED
tests/test_kayak_source.py::test_extract_disables_model_thinking PASSED
tests/test_kayak_source.py::test_extract_states_the_departure_date_in_the_prompt PASSED
tests/test_kayak_render_config.py::test_launch_args_expose_a_webgl_context PASSED
======================= 57 passed, 1 deselected in 2.70s =======================
```

### Full suite

```
337 passed, 3 deselected in 27.48s
```

### `docker compose ps` + one real `search_and_store` (user-requested check)

No image rebuild was needed this phase — the service is Active dev, so the
`.:/app` mount plus `--reload` made every code change live immediately.
Checked anyway after the changes:

```
NAME              IMAGE                             COMMAND                  SERVICE           CREATED       STATUS                 PORTS
airfare-monitor   airfare-monitor-airfare-monitor   "/app/docker-entrypo…"   airfare-monitor   2 hours ago   Up 2 hours (healthy)   0.0.0.0:8100->8100/tcp, [::]:8100->8100/tcp

search_and_store(21) completed in 2.3s

id    searched_at          rows  best
6261  2026-08-05 07:12:31  7     728.0
6260  2026-08-05 06:01:53  7     726.0

INFO   search_done   21   7 results  2026-08-05 07:12:31
INFO   search_start  21              2026-08-05 07:12:29
INFO   search_done   20   7 results  2026-08-05 06:01:53
```

Run against tracker 21 (`kayak_enabled=0`) so the check costs no live Kayak
request. Tracker 20's 06:01:53 row is its normal `fli` search — unaffected by
the Kayak deferral.

## Commits

- `82f2ed9` — `[phase-3.1] Expose a WebGL context in the Kayak launch args`
- `cc85fc5` — `[phase-3.2] Trim the Kayak body to the results section before extraction`
- `fef9bec` — `[phase-3.3] Disable model thinking on the Kayak extraction call`

(`acb0182`, the user's own commit, pinned 3.1 with a test and amended the
plan to drop Step 0 and merge Step 4 into Step 2.)

## Deviations from the plan

1. **Phase 3 declares "Files: None — experiment only"; three code commits
   landed.** Step 1's own text mandates the first ("Fix any self-own here
   before spending a single live attempt"), and the user approved it before
   any live request; the orchestrator then folded it into the plan as task
   3.1. Tasks 3.2/3.3 were not anticipated by the plan at all — they were
   forced by the discovery that extraction, not evasion, was what made
   attempts fail. Both were user-directed (3.2 explicitly: "trim the body to
   the results section instead of raising the timeout"; 3.3 from the user's
   pointer to DeepSeek's docs).
2. **Step 0 dropped, Step 4 merged into Step 2** — user decision, recorded in
   the plan itself (`acb0182`).
3. **Tracker 20 delayed rather than disabled for the run**, per the user's
   choice among the three options offered; then disabled afterwards for the
   independent reason in "Blockers for Step 5".
4. **Step 3 (C5 ceiling test) not run** — it is conditional on Step 2
   failing, and Step 2 passed.
5. **Step 5 not started** — out of scope for "phase 3 only", and blocked
   regardless.

## Test gaps

**Nine tests added that the orchestrator did not write** (discovery gaps, all
flagged rather than quietly added): seven for `_results_section` and two for
`_extract`'s request shape. Rationale: 3.2 and 3.3 are behaviour the plan
never anticipated, and both are silently-reversible — dropping the
`extra_body` parameter or the trim call reverts Kayak to timing out on
roughly half of all attempts, with no test failing to say so. One of my own
first-draft assertions was wrong (`trimmed.count("Select") == 5` counts the
airline filter's "Select all" label as a substring); the function was
correct, so I fixed the assertion to count marker *lines*, not the function.

**No orchestrator test was modified, weakened, or deleted.**

**Still unpinned, carried over from Phase 2's report:** the
`search()` → `capture_sample` wiring has no direct test. Attempt 7 showed one
concrete consequence (no sample on a hung render) that a test would have
caught.

## Follow-ups (noted, not done)

- **The three Step 5 blockers above** — currency, `flight_number`, latency
  tail. Currency and `flight_number` both need a decision before Kayak writes
  to any tracker.
- **Move sample capture to cover a hung render**, or record a body-less
  sidecar on the timeout path, so no attempt goes unrecorded.
- **Throwaway files left under `data/`** (gitignored, safe to delete, not
  removed unasked): `step1_fingerprint.py`, `step1_webgl.py`,
  `step1_kayak_check.py`, `experiment_table.py`, and the profile dirs
  `kayak-profile-fpcheck/` and `kayak-profile-smoke/` (the latter from
  Phase 2). The bundle's real profile `data/kayak-profile/` is live and
  should be kept — it is warm and part of what passed.
- **Sample retention is still unbounded** (Phase 2 follow-up, now with 9 more
  bodies).
- **Xvfb is still unsupervised** (Phase 2 follow-up).
- **The bundle is stateful.** All 10 attempts shared one profile that started
  cold, so "warm profile" is part of what passed. A future arm should reset
  it deliberately.
- **n=10 cannot resolve 0% from ~10%.** 0/10 is strong evidence the bundle
  works and weak evidence about the exact rate.

## Confidence

**certain** on the headline: 0/10 blocked, with 9 captured bodies on disk
showing full results pages and 4 complete extractions. That is reproducible
from the samples and does not depend on my interpretation.

**likely-good** on the extraction fixes: 3.2 and 3.3 are measured against the
live endpoint and pinned by tests, but the 32s outlier means the 30s budget
is not proven safe under all conditions.

**needs-review** on promotion readiness: the currency and `flight_number`
defects are confirmed and unfixed, and either would put wrong data into a
tracked route's history. Kayak must stay off tracker 20 until both are
resolved.
