# Plan 018 — Get Kayak past PerimeterX: bundled evasion stack + measurement harness

## Context

Plan 017 shipped Kayak end-to-end and Phase 6 established the pipeline works
mechanically, but **zero successful extractions** across 5 live attempts,
with at least one confirmed bot-detection interstitial. Decision 9 of plan
017 deferred reliability tuning to a follow-up; this is that follow-up.

**The decisive evidence** (user, 2026-08-05): browsing Kayak **manually from
the same residential IP** (`177.145.72.252`, home WAN via `192.168.1.1`, not
the VPS), with many successive and repetitive queries, is **never blocked**.
Playwright from that same IP is blocked immediately.

That rules out, without further testing:
- **IP reputation** — identical IP works manually
- **Request rate** — manual hammering is fine
- **Cadence as a mitigation** — plan 017's 3h spacing was an arbitrary number
  and buys nothing against PerimeterX. It stays only as a politeness/load
  choice, not a detection countermeasure.

What remains is the **client fingerprint and behaviour**. PerimeterX is
classifying the automation, not the traffic.

**The current render is the most detectable configuration possible**:
`p.chromium.launch(headless=True)` with no launch args, no user agent, no
locale, no timezone, no viewport, a fresh incognito context per call, and a
`goto` → `inner_text` with zero interaction. No evasion is attempted at all.
Being blocked is the expected outcome, and there is a lot of headroom.

### How detection works (ranked by likely contribution here)

1. **CDP artifacts.** Playwright drives Chromium over the DevTools Protocol
   and calls `Runtime.enable` to track execution contexts. That is observable
   from page JS — a getter on a property CDP's serialization touches fires
   only under automation. It works regardless of headless/headful and
   regardless of how well everything else is spoofed. This is what
   `patchright` (task 2.3) exists to patch.
2. **`navigator.webdriver === true`**, set by Chromium under automation.
3. **Headless fingerprint** — SwiftShader software WebGL renderer instead of
   a real GPU string, `window.outerWidth/outerHeight === 0`, minimal font
   set, missing proprietary codecs, thin `navigator.plugins`.
4. **Zero behavioural telemetry** — PerimeterX scores mouse/scroll/timing
   events. `goto` → read emits none; a human session emits thousands.
5. **No profile state** — no cookies, no `_px3` token, no localStorage.

TLS/JA3 is a non-issue: real Chromium presents a genuine TLS fingerprint.

---

## Decisions

1. **Bundle, don't bisect.** The user explicitly does not care which
   technique Kayak uses. C1–C4 (below) are implemented and tested together
   as one deployable stack. If it works, ship it; no attribution work.
2. **C5 is excluded from the bundle and held as a ceiling test.** C5
   (attach to a manually-launched Chrome with the real user profile) has no
   unattended form, so it cannot ship. Bundling it would make a green result
   uninterpretable — you would not know whether the *deployable* subset
   works. Run it only if C1–C4 fails, to answer "is this reachable at all?"
   before investing further.
3. **Keep the offline fingerprint smoke test.** Not for attribution — to
   catch a *self-inconsistent* bundle. A UA still advertising `HeadlessChrome`,
   or a 0x0 viewport, is more suspicious than no override at all. Costs zero
   Kayak requests.
4. **Derive the fingerprint, don't hardcode it — and pin the English site.**
   The user agent must come from the actual launched browser build (a
   hardcoded UA silently rots on the next image rebuild and becomes a
   *signal* rather than a disguise). **`timezone_id`** must match the egress
   IP's geography, since it is OS-derived and trivially cross-checked; it is
   the one field to update on relocation. **Locale is deliberately pinned to
   English regardless of egress** — see task 1.8. Language preference and
   physical location are independent facts about a real person, so requiring
   them to agree would buy nothing and would cost a stable parsing surface.
5. ~~NordVPN is an experiment-phase tool~~ — **dropped 2026-08-05.** The
   user has a subscription but no client is installed on `minnie`, and
   installing one is out of scope. The experiment runs on the residential
   IP, which is also the production egress. See Phase 3 Step 0.
6. **Experiments never touch tracker 20.** A throwaway route/date, so
   experiments cannot pollute the tracked route's price history or its
   reputation.
7. **Short experiment spacing is justified** by the manual-browsing
   evidence (rate is not the trigger). ~10 min between attempts during
   experimentation. Production cadence is a separate, unrelated choice.

---

## Phase 1 — Config seam + fingerprint construction

### Intent
Make the entire evasion stack a **parameter object** rather than six edits
scattered through `_render`, so the bundle can be trimmed, disabled, or
extended without touching render logic — and so every pure part of it is
unit-testable with no browser. Out of scope: any live Kayak request.

### Tasks
1.1 `backend/sources/kayak.py`: add a `KayakRenderConfig` dataclass —
    `headless: bool`, `user_data_dir: str | None`, `locale: str`,
    `timezone_id: str`, `viewport: dict`, `warmup_url: str | None`,
    `warmup_dwell_s: tuple[float, float]`, `stealth: bool`. Defaults = the
    C1–C4 bundle, with `locale` English and `warmup_url` on `kayak.com`
    (1.8). `KayakSource.__init__` takes an optional config so tests
    and experiments can vary it.
1.2 `_launch_args(config) -> list[str]` (pure): includes
    `--disable-blink-features=AutomationControlled`. **Must not** include
    `--enable-automation`. Keep this a pure function returning a list so its
    contents are assertable without launching anything.
1.3 `_context_options(config, browser) -> dict` (pure given a UA string):
    `locale`, `timezone_id`, `viewport`, `user_agent`. The UA is **derived
    from the launched browser's own version string** with the `HeadlessChrome`
    token rewritten to `Chrome` — never hardcoded (Decision 4).
1.4 `_fingerprint_is_consistent(options) -> bool` (pure): asserts the
    invariants the smoke test exists to protect — UA contains no
    "Headless"/"Playwright" token, `timezone_id` is actually set, viewport is
    a plausible desktop size. It must **not** require locale and timezone to
    agree on region (see 1.8) — that rule would reject the shipped
    configuration. Used by a unit test and by the Phase 3 smoke step.
1.5 `_render` uses `launch_persistent_context(user_data_dir=...)` when
    `user_data_dir` is set (C3), else `launch()` + `new_context()`. Profile
    dir defaults under `data/` and **must be gitignored**.
1.6 Warm-up (C3): when `warmup_url` is set, navigate there first, dwell a
    random duration inside `warmup_dwell_s`, then navigate to the search
    URL. A `_warmup_sequence(config)` helper returning the ordered list of
    (url, dwell) steps keeps the ordering assertable without a browser.
1.7 Behavioural noise (C4-adjacent): a small scroll and mouse move before
    reading the DOM. Keep as a separate `_simulate_interaction(page)` so it
    can be mocked out.
1.8 **Pin the English site; let timezone track geography.** The parsing
    surface stays `kayak.com` in English **for the life of the project**,
    independent of where the deployment sits — one page language, one price
    format, one set of button labels, no re-tuning when the host moves from
    Brazil to Switzerland.
    This does not weaken the fingerprint. Language preference and physical
    location are independent facts about a real person: an English-preferring
    resident of Brazil (or Switzerland) is entirely ordinary. What *is*
    cross-checkable against IP geolocation is **timezone**, which is
    OS-derived — so `timezone_id` must be set deliberately to match the
    egress geography and updated on relocation. It cannot be auto-derived
    from the container, which reports **UTC** (verified 2026-08-05); falling
    through to UTC would itself be a mismatch against any residential egress.
    Consequently `_fingerprint_is_consistent` must **not** require locale and
    timezone to agree on region — that rule would reject the shipped
    configuration. It checks: no Headless/Playwright token in the UA, a
    plausible desktop viewport, and a timezone that is actually set.
1.9 **Price grounding accepts both separator conventions, unconditionally.**
    `_price_grounded` builds `{str(n), f"{n:,}"}` — `"4312"` and `"4,312"`.
    A four-digit fare on a non-English page renders `R$ 4.312` (dot
    thousands) or `4.312,00` (comma decimals), matching neither, so **every
    expensive itinerary would be dropped as hallucinated** — silent, and
    indistinguishable from a clean empty extraction. Even with the English
    site pinned, accept all three renderings rather than branching on locale:
    the fallback costs nothing and survives a redirect.
1.10 **Result-button markers are a set, not a locale lookup.**
    `_wait_for_results_stable` polls `page.get_by_text("Select", exact=True)`
    and task 2.5's structural signal keys off the same token. If Kayak
    force-redirects by IP geography, that button becomes "Selecionar" or
    "Auswählen", and a hardcoded `"Select"` would (a) poll zero forever,
    burning the full 45s render cap on every attempt, and (b) make the
    structural signal classify every real results page as blocked. Match a
    module-level `_RESULT_MARKERS` set with `any()` — no config plumbing, no
    locale coupling, survives both a redirect and the relocation.
    **1.8-1.10 must land together**, or the first live arm measures a broken
    harness rather than the evasion bundle.

### Files
- Modify: `backend/sources/kayak.py`, `.gitignore`
- New tests: see below

### What NOT to touch
- `_extract`, `_validate`, `_map_result`, `search()`'s control flow — this
  phase changes *how the page is fetched*, nothing downstream.
- `backend/scheduler.py` — cadence is not a countermeasure (Context), so
  nothing about the due-check changes here.

### Tests (all offline, no browser — written, 20 failing as specified)
`tests/test_kayak_render_config.py` (new). It carries an API contract in its
header the implementer must follow, because the plan left two things open:
`_context_options(config, default_ua)` takes the browser's **default user
agent string**, not a `Browser` object (that is what keeps it pure), and
`_warmup_sequence(config)` returns only the **pre-search** steps, so it is
empty when warm-up is off.

- `test_launch_args_disable_automation_controlled_blink_feature`
- `test_launch_args_do_not_enable_automation`
- `test_context_options_derive_user_agent_from_browser_version` (two builds
  in, two different UAs out — proves derivation, not a hardcoded string)
- `test_derived_user_agent_strips_headless_token`
- `test_fingerprint_consistent_for_default_config`
- `test_fingerprint_inconsistent_when_user_agent_says_headless`
- `test_fingerprint_allows_english_locale_with_a_non_english_timezone`
  (pins that the shipped configuration is not rejected by its own check)
- `test_fingerprint_inconsistent_when_timezone_is_missing`
- `test_fingerprint_inconsistent_for_headless_default_viewport`
- `test_warmup_sequence_visits_homepage_before_search_url`
- `test_warmup_sequence_empty_when_warmup_url_not_set`
- `test_warmup_dwell_is_not_always_the_same_value`
- `test_simulate_interaction_emits_mouse_and_scroll_events`
- `test_result_markers_include_english_and_localized_variants` (1.10)
- `test_config_defaults_to_the_c1_c4_bundle` (also pins that C5 is not
  reachable through config, per Decision 2)
- `test_kayak_source_accepts_a_render_config`
- `test_kayak_source_defaults_to_the_bundle_config`

Added to `tests/test_kayak_source.py` for 1.9:
- `test_validate_keeps_row_whose_price_uses_dot_thousands_separator`
- `test_validate_keeps_row_whose_price_uses_comma_decimals`

### Success criteria
All of the above pass; full suite still green.

### Verification
```bash
pytest tests/test_kayak_render_config.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/018-phase-1.md`.

---

## Phase 2 — Headful under Xvfb, the CDP patch, and the sample harness

### Intent
The two bundle rungs that need infrastructure (C2 headful, C4 CDP-leak
patch), plus the capture harness without which no experiment is
interpretable. Out of scope: running the experiment (Phase 3).

### Tasks
2.1 ~~`Dockerfile`: add `xvfb`~~ — **already satisfied, verified 2026-08-05**:
    `playwright install --with-deps chromium` (Phase 5 of plan 017) already
    pulled it in, `which Xvfb` → `/usr/bin/Xvfb`. **No Dockerfile change and
    no image rebuild are needed for this**, which removes most of the restart
    risk this phase was flagged for. Container already has `shm_size: 1gb`
    and a 1.5G limit with ~150MB in use, so the headroom is there.
    What is missing is only that Xvfb is never *started* and `DISPLAY` is
    unset — see 2.2. Confirmed empirically: a headful launch in the container
    today exits with code 1.
2.2 `docker-compose.yml`: `DISPLAY=:99`; start Xvfb alongside uvicorn (a
    tiny entrypoint script, or `xvfb-run`). Must not break `--reload`.
2.3 **CDP-leak patch — use `patchright==1.61.2`** (C4).
    **Corrected 2026-08-05.** This task originally named
    `rebrowser-playwright` and claimed "import sites stay identical". Both
    were wrong, and neither had been verified when written:
    - `rebrowser-playwright`'s newest release is **1.52.0**, so pinning it
      "as the current `playwright==1.62.0` is" would mean a 10-version
      downgrade plus an older bundled Chromium.
    - The wheel installs a **`rebrowser_playwright`** top-level module, so
      the import changes either way.

    `patchright` fixes the same class of leak (`Runtime.enable` /
    `Console.enable`) while tracking the current Playwright generation
    (1.61 vs 1.62), so it delivers this task's *intent* at a one-version
    gap instead of ten.

    **Why not the `playwright-stealth` fallback:** it patches JS-visible
    properties only and does **not** touch the CDP leak — the factor this
    plan ranks #1. Shipping it would mean running Phase 3 believing C4 is
    under test when it isn't, and misattributing the result. If patchright
    proves unworkable, **defer C4 and say so in the report** rather than
    substituting something that doesn't do the job.

    Scope, verified 2026-08-05:
    - **One** real import site: `backend/sources/kayak.py:235`
      (`from playwright.async_api import async_playwright`). The
      `"playwright"` string in `_fingerprint_is_consistent` is a UA check,
      not a package reference — leave it. The `rebrowser-playwright` mention
      in `KayakRenderConfig`'s docstring is now stale; correct it here.
    - `Dockerfile`: `playwright install --with-deps chromium` →
      `patchright install --with-deps chromium`. **Install one browser set,
      not two** — the existing `/root/.cache/ms-playwright` is already 656MB
      and nothing else in the codebase launches a browser. Confirm whether
      `patchright` pulls `playwright` as a dependency before deciding
      whether `playwright==1.62.0` stays in `requirements.txt`.
    - This phase's Verification block below still imports `playwright` —
      update it too.

    **Sequence this task LAST within Phase 2.** 2.2 and 2.4-2.7 are
    independent of it, so a dependency problem here must not block the Xvfb
    fix, the sample harness, or the UA memoization.
2.4 **Sample capture harness.** On every Kayak attempt, persist the rendered
    body to `data/kayak-samples/{iso-timestamp}.txt` plus a JSON sidecar:
    config id, blocked verdict, body length, `"Select"` occurrence count,
    extraction row count, final outcome. Gitignored. Without this, any
    marker change makes past samples unre-classifiable — which is exactly
    what went wrong in plan 017 Phase 6.
2.5 **Structural block signal**, complementing `_looks_blocked`'s markers:
    a real results page is long and contains many `"Select"` occurrences; an
    interstitial is short with zero. Roughly `len(body) < 2000 and "select"
    not in body.lower()`. Markers catch the page we've seen; this catches the
    next rewrite. Keep it pure and separately testable.
2.6 A small runner script (not a pytest) that performs N attempts at a given
    spacing against a **throwaway route**, writing samples via 2.4 — this is
    what Phase 3 actually executes.
2.7 **Memoize the derived user agent.** Phase 1's `_render` launches a
    throwaway headless Chromium on *every* attempt purely to read
    `navigator.userAgent`, then launches the real browser — two Chromium
    launches per render. The UA cannot change until the image is rebuilt, so
    cache it at module level after the first probe. This is not
    micro-optimisation: the `Connection closed while reading from the driver`
    crash has now fired **twice** (2026-08-04 23:08, 2026-08-05 03:37, each
    leaving a ~190MB core dump), and doubling the process spawns doubles the
    exposure to whatever tears those workers down.

### Files
- Modify: `Dockerfile`, `docker-compose.yml`, `requirements.txt`,
  `backend/sources/kayak.py`, `.gitignore`
- New: sample-capture module, experiment runner script

### What NOT to touch
- Tracker 20, or anything reading from the live DB. The runner writes only
  to `data/kayak-samples/`.

### Tests (written, 7 failing as specified)
`tests/test_kayak_samples.py` (new). Contract: `capture_sample(body_text,
record, samples_dir) -> Path | None` writes `<iso>.txt` (body) and
`<iso>.json` (record plus derived fields), returning the body path or `None`
on any failure.

- `test_structural_signal_flags_short_page_with_no_select_occurrences`
- `test_structural_signal_does_not_flag_long_results_page`
- `test_structural_signal_does_not_flag_long_page_that_merely_lacks_markers`
  — the signal must key on "short AND no action buttons", never on "no known
  marker matched"; a redesign or unexpected locale is not evidence of a block
- `test_structural_signal_recognises_localized_action_buttons` (1.10)
- `test_sample_capture_writes_body_and_sidecar`
- `test_sample_sidecar_records_config_id_and_blocked_verdict`
- `test_sample_capture_survives_unwritable_directory` (capture is telemetry,
  not the job — a search must never fail because a sample could not be
  written)
- `test_two_samples_in_the_same_second_do_not_overwrite_each_other` — a lost
  sample is a lost data point that cost a real request

### Success criteria
Tests pass; container rebuilds and reaches `healthy`; headful Chromium
launches inside it; full suite green.

### Verification
```bash
docker compose up -d --build && docker compose ps
docker exec airfare-monitor python -c "
import asyncio
from patchright.async_api import async_playwright   # patchright after 2.3; playwright before it
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        print('headful OK:', b.version); await b.close()
asyncio.run(m())"
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/018-phase-2.md`.

---

## Phase 3 — Run the experiment

### Intent
Answer one question: **does the C1–C4 bundle get through?** No attribution,
no per-rung analysis unless the bundle fails.

### Step 0 — ~~validate the VPN test bed~~ — **dropped 2026-08-05**
The user has a NordVPN *subscription*, but no VPN client is installed on
`minnie` and none was implied. Installing one is a change outside
`/srv/airfare-monitor` and needs their hands for the manual browse, so this
step cannot run as written.

**The experiment runs on the residential IP** — the plan's own stated
fallback, and on reflection the better arm regardless:
- It is also the **production** egress, so Steps 2 and 4 collapse into one.
  A pass needs no separate re-validation on a different IP.
- NordVPN exits are datacenter IPs and often pre-flagged, so a failed arm
  through the VPN could be the VPN rather than the config — the confounder
  this step existed to bound would have been *introduced* by using it.
- The reputation cost is small and bounded: 10 requests over ~100 minutes,
  from an IP that already sustains heavy manual browsing without a block.

Accepted risk: if the bundle is still detected, those are 10 bot-flagged
events on the residential IP. Small against the manual-browsing volume that
IP already carries, but it is the reason not to re-run the experiment
casually.

### Step 1 — offline fingerprint smoke test (zero Kayak requests) — **DONE 2026-08-05**
Result: clean on `navigator.webdriver` (false), all sannysoft tests,
`outerWidth` 1928 (headless reports 0), 5 plugins, timezone
`America/Sao_Paulo`, locale `en-US`, creepjs 0% headless / 0% stealth, and
`_fingerprint_is_consistent` agreeing. WebRTC confirmed egress
`177.145.72.252` — the residential IP.

**One self-own found and fixed before any live attempt** (task 3.1 below) —
which is exactly what this step exists for.
Point the configured browser at `bot.sannysoft.com` and
`abrahamjuliot.github.io/creepjs`; capture results. Confirm no
"Headless"/webdriver flags and that `_fingerprint_is_consistent` agrees.
**Fix any self-own here before spending a single live attempt.**

3.1 **Expose a WebGL context.** The bundle rendered with *no* WebGL context
    at all — sannysoft "Canvas has no webgl context", creepjs reporting
    params/exts/gpu blocked. That is a **harder** automation tell than the
    SwiftShader renderer string this plan ranked #3: every real Chrome has a
    context, falling back to SwiftShader on a GPU-less machine rather than
    exposing none. Add `--use-gl=angle --use-angle=swiftshader` to
    `_launch_args`; probed to restore 36 extensions and an
    `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device...))` vendor string,
    and it violates neither existing `_launch_args` test. Pinned by
    `test_launch_args_expose_a_webgl_context`.

Also confirm here, cheaply, that **`kayak.com` does not force-redirect to a
local domain** from the egress IP in use. If it does, task 1.10's marker set
is what keeps the harness working, but the LLM extraction prompt should be
checked against the redirected page's language before the arm is trusted.

### Step 2 — the bundle against Kayak

**Route:** a throwaway that is *not* tracked by any tracker — e.g.
`GRU→LIS`, departing ~60 days out. Never `GRU→ZRH` or `GRU→GVA`
(trackers 20/21/27). Use the same route for every attempt so route
popularity isn't a hidden variable, and keep the same date rather than
rolling it.

**Volume and spacing:** 10 attempts, ~10 min apart, ≈100 min total. Spacing
is justified by the manual-browsing evidence that rate is not the trigger
(Context); it is not a claim that rate never matters.

**Per-attempt record** (one JSON line, written by the Phase 2 harness):
```
attempt_n, iso_timestamp, egress_ip, config_id, blocked_by_markers,
blocked_by_structure, body_len, select_count, extracted_rows,
validated_rows, outcome, sample_path, elapsed_s
```
`egress_ip` matters: if NordVPN drops mid-run the arm silently changes
meaning, and this is the only way to notice after the fact.

**Run it detached** — ~100 min exceeds any sane foreground wait — and let it
write incrementally so a crash doesn't lose collected samples.

**Do not touch tracker 20 during the run.** Its scheduled job also calls
Kayak; a natural-cadence attempt landing mid-experiment would both pollute
the sample and double the request rate from that IP. Either pause tracker 20
(`kayak_enabled=0`) for the duration and re-enable after, or confirm its
`kayak_next_due_at` falls outside the window before starting.

**Read the result as:**
- **0–1 blocks / 10** → success. Go to Step 5 (Step 4 is merged in).
- **2–7 / 10** → partial. Usable with retries; consider whether a retry on
  block (respecting a cap) is worth adding before trimming anything.
- **8–10 / 10** → failed. Go to Step 3.

At n=10 this distinguishes "works" from "doesn't"; it cannot resolve 40% vs
60%, so do not over-read the middle band.

### Step 3 — ceiling test — **NOT RUN, and now moot**
Step 2 passed at 0 blocks / 10, so the C5 ceiling test has nothing left to
answer. It existed only to distinguish "the bundle is missing something"
from "the barrier isn't the fingerprint" in the event of failure. Do not
run it.

<details><summary>Original text, retained for the record</summary>

#### (only if Step 2 had failed)
C5: launch Chrome manually with `--remote-debugging-port=9222` using the
real profile, attach via `connect_over_cdp`, run 2–3 attempts. **This is
diagnostic only and cannot ship** (Decision 2).
- C5 passes → the automation fingerprint is the barrier and the bundle is
  missing something; worth another iteration.
- C5 also fails → the barrier isn't the fingerprint. Stop investing in
  evasion and reconsider the approach entirely (different surface, a paid
  flight-data API, or dropping Kayak).

### Step 4 — ~~validate on the production IP~~ — **merged into Step 2**
Step 2 now runs on the residential IP, which *is* the production egress, so
there is no change of egress left to validate. Skip straight to Step 5.

</details>

### Step 5 — promote — **BLOCKED, deferred to its own plan**
Step 2 answered the question this plan set out to answer. Promotion is
blocked on three data-correctness defects that only became *observable* once
pages started rendering — plan 017 Phase 6 was 0/5 renders, so the
extraction path had never once run against real Kayak data. Two of the three
are design decisions, not patches:

1. **Currency is not what we asked for.** Verified independently: all 9
   captured bodies show `United States dollar` and `$`-prefixed prices
   despite `?currency=EUR`. `_map_result` stamps the *tracker's* currency, so
   promoting as-is writes USD values labelled EUR. Root cause is an open
   question plan 017 task 2.3 raised and never closed ("confirm the real
   currency param name during implementation — the prototype ran USD-default
   and didn't need to test this").
2. **Flight identity.** Kayak's collapsed results list does not print flight
   numbers; the model returns `""`, `"N/A"`, `"unknown"`, `"AT"` for the same
   flight across runs. This fragments Kayak's own history — and, more
   fundamentally, means **plan 017 Phase 1's cross-source merge does not
   actually work for Kayak**. Phase 1 dropped `source` from `flight_key` so
   one physical flight from Google and Kayak would share an identity, but
   `airline|flight_number|departure_time` can never match Google's
   `TAP AIR PORTUGAL|TP 84|…` when Kayak supplies no number at all. The
   phantom new/missing duplication Phase 1 existed to prevent returns for a
   different reason.
3. **Extraction latency tail** — 1 of 6 thinking-disabled runs hit 32s
   against a 30s cap. Degrades gracefully; lowest severity of the three.

Also outstanding before any further live run:
- **Harness gap:** a render that hangs to `_OVERALL_TIMEOUT_S` produces no
  sample at all (attempt 7), so task 2.4's "record every attempt" is unmet
  on precisely the path where a body would be most diagnostic.
- **Unmeasured claim:** the 3.2/3.3 extraction fixes were validated against
  *captured* bodies, never live. "4/9 → ~9/9" is a reasonable inference, not
  a measurement.

<details><summary>Original Step 5 text</summary>
Only after Step 2 passes: re-enable Kayak on tracker 20, revisit plan 017's tasks 6.3/6.4
(which were confounded by the unrelated `fast_flights` TypeError), and
finally close 017's Phase 6 with a real success sample and the 6.6 hand
spot-check against kayak.com.

</details>

### Files
None — experiment only.

### Success criteria
A recorded, dated block-rate figure for the bundle on both VPN and
residential egress, and an explicit go/no-go on shipping it.

### Verification
Sample files under `data/kayak-samples/` plus a results table in
`.agent/reports/018-phase-3.md` — one row per attempt: timestamp, egress,
config, blocked verdict, body length, outcome.

---

## Known confounders

- **The bundle is stateful.** A persistent profile means attempt N+1 is not
  independent of attempt N. Reset the profile dir between distinct arms, and
  note that a warm profile is part of what's being tested.
- ~~NordVPN egress is itself a variable~~ — moot: the experiment runs on
  the residential/production IP, so there is no egress difference between
  the measurement and the deployment.
- ~~The `fast_flights` TypeError~~ — **fixed 2026-08-05** before this plan
  starts (`_to_iso` degrades to `""` on a `None` date/hour component instead
  of raising out of the whole fetch). It confounded 017's 6.3/6.4 by making
  both observed Kayak cycles produce genuinely empty snapshots; Step 5
  should now be able to observe Kayak failing *while* the main sources
  succeed, which is the scenario 6.4 needs.
- **n=10 resolution**, as above.

## Handoff notes

- Read plan 017 first, particularly "Why Kayak shares the main snapshot" and
  Decision 9 — this plan is that deferred follow-up.
- `.agent/reports/017-phase-6.md` has the captured interstitial text, the
  driver-crash core-dump finding, and the sample table this continues.
- The live service is Active dev: editing `backend/` deploys instantly.
  Anything that can break `search_and_store` breaks price collection for all
  6 active trackers — see the `KeyError: 'kayak_enabled'` incident recorded
  in `CLAUDE.md`. Phase 2's Dockerfile/compose work needs a rebuild, so plan
  for a short restart window.
- Kayak's ToS prohibit automated access; plan 017 Decision 10 records this
  as an accepted, deliberate tradeoff at personal-use volume. Experiment
  spacing here is compressed *for the experiment*; it is not a licence to
  raise production volume.
