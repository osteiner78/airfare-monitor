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
   `rebrowser-playwright` exists to patch.
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
   catch a *self-inconsistent* bundle. A hardcoded UA that doesn't match the
   real Chromium build, or `pt-BR` against a UTC timezone, is more
   suspicious than no override. Costs zero Kayak requests.
4. **Derive the fingerprint, don't hardcode it.** The user agent must come
   from the actual launched browser build, and locale/timezone/geolocation
   must be mutually consistent and consistent with the egress IP's
   geography (Brazil). A hardcoded UA silently rots on the next Playwright
   image rebuild and becomes a *signal* rather than a disguise.
5. **NordVPN is an experiment-phase tool only**, per the user's constraint.
   Production runs on the residential IP. See Phase 3 Step 0 — the VPN must
   itself be validated before being trusted as a test bed.
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
    C1–C4 bundle. `KayakSource.__init__` takes an optional config so tests
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
    "Headless"/"Playwright" token, timezone and locale agree on region,
    viewport is a plausible desktop size. Used by a unit test and by the
    Phase 3 smoke step.
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

### Files
- Modify: `backend/sources/kayak.py`, `.gitignore`
- New tests: see below

### What NOT to touch
- `_extract`, `_validate`, `_map_result`, `search()`'s control flow — this
  phase changes *how the page is fetched*, nothing downstream.
- `backend/scheduler.py` — cadence is not a countermeasure (Context), so
  nothing about the due-check changes here.

### Tests (all offline, no browser)
`tests/test_kayak_render_config.py` (new):
- `test_launch_args_disable_automation_controlled_blink_feature`
- `test_launch_args_do_not_enable_automation`
- `test_context_options_derive_user_agent_from_browser_version`
- `test_derived_user_agent_strips_headless_token`
- `test_fingerprint_consistent_for_default_config`
- `test_fingerprint_inconsistent_when_user_agent_says_headless`
- `test_fingerprint_inconsistent_when_locale_and_timezone_disagree`
- `test_warmup_sequence_visits_homepage_before_search_url`
- `test_warmup_sequence_empty_when_warmup_url_not_set`
- `test_config_defaults_to_the_c1_c4_bundle`

### Success criteria
All of the above pass; full suite still green.

### Verification
```bash
pytest tests/test_kayak_render_config.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/018-phase-1.md`.

---

## Phase 2 — Headful under Xvfb, rebrowser, and the sample harness

### Intent
The two bundle rungs that need infrastructure (C2 headful, C4 CDP-leak
patch), plus the capture harness without which no experiment is
interpretable. Out of scope: running the experiment (Phase 3).

### Tasks
2.1 `Dockerfile`: add `xvfb` so Chromium can run headful. Container already
    has `shm_size: 1gb` and a 1.5G limit with ~150MB in use, so the headroom
    is there.
2.2 `docker-compose.yml`: `DISPLAY=:99`; start Xvfb alongside uvicorn (a
    tiny entrypoint script, or `xvfb-run`). Must not break `--reload`.
2.3 Swap `playwright` for `rebrowser-playwright` in `requirements.txt`
    (C4 — patches the `Runtime.enable` CDP leak). Import sites stay
    identical; **pin the version** as the current `playwright==1.62.0` is.
    If the swap proves disruptive, `playwright-stealth` is the fallback —
    weaker, but additive rather than a fork.
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

### Files
- Modify: `Dockerfile`, `docker-compose.yml`, `requirements.txt`,
  `backend/sources/kayak.py`, `.gitignore`
- New: sample-capture module, experiment runner script

### What NOT to touch
- Tracker 20, or anything reading from the live DB. The runner writes only
  to `data/kayak-samples/`.

### Tests
`tests/test_kayak_samples.py` (new):
- `test_structural_signal_flags_short_page_with_no_select_occurrences`
- `test_structural_signal_does_not_flag_long_results_page`
- `test_structural_signal_does_not_flag_long_page_that_merely_lacks_markers`
- `test_sample_capture_writes_body_and_sidecar`
- `test_sample_sidecar_records_config_id_and_blocked_verdict`
- `test_sample_capture_survives_unwritable_directory` (capture must never
  take down a search)

### Success criteria
Tests pass; container rebuilds and reaches `healthy`; headful Chromium
launches inside it; full suite green.

### Verification
```bash
docker compose up -d --build && docker compose ps
docker exec airfare-monitor python -c "
import asyncio
from playwright.async_api import async_playwright
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

### Step 0 — validate the test bed (before anything else)
Browse Kayak **manually through NordVPN**. NordVPN exits are datacenter IPs
and many are pre-flagged. If manual browsing through the VPN is blocked, the
VPN is unusable here — every arm would fail for the wrong reason, and the
experiment runs on the residential IP instead, accepting the reputation risk.

### Step 1 — offline fingerprint smoke test (zero Kayak requests)
Point the configured browser at `bot.sannysoft.com` and
`abrahamjuliot.github.io/creepjs`; capture results. Confirm no
"Headless"/webdriver flags and that `_fingerprint_is_consistent` agrees.
**Fix any self-own here before spending a single live attempt.**

### Step 2 — the bundle against Kayak
~10 attempts, ~10 min spacing, throwaway route/date, via NordVPN if Step 0
passed. Record every attempt through the Phase 2 harness.

**Read the result as:**
- **0–1 blocks / 10** → success. Go to Step 4.
- **2–7 / 10** → partial. Usable with retries; consider whether a retry on
  block (respecting a cap) is worth adding before trimming anything.
- **8–10 / 10** → failed. Go to Step 3.

At n=10 this distinguishes "works" from "doesn't"; it cannot resolve 40% vs
60%, so do not over-read the middle band.

### Step 3 — ceiling test (only if Step 2 failed)
C5: launch Chrome manually with `--remote-debugging-port=9222` using the
real profile, attach via `connect_over_cdp`, run 2–3 attempts. **This is
diagnostic only and cannot ship** (Decision 2).
- C5 passes → the automation fingerprint is the barrier and the bundle is
  missing something; worth another iteration.
- C5 also fails → the barrier isn't the fingerprint. Stop investing in
  evasion and reconsider the approach entirely (different surface, a paid
  flight-data API, or dropping Kayak).

### Step 4 — validate on the production IP
Winning config, VPN off, residential IP, 5–10 attempts at production-ish
spacing, still on the throwaway route. Confirms the result survives the
change of egress.

### Step 5 — promote
Only after Step 4: enable on tracker 20, revisit plan 017's tasks 6.3/6.4
(which were confounded by the unrelated `fast_flights` TypeError), and
finally close 017's Phase 6 with a real success sample and the 6.6 hand
spot-check against kayak.com.

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
- **NordVPN egress is itself a variable.** Step 0 exists to bound this; a
  Step 2 pass through VPN still needs Step 4 to confirm on the real IP.
- **The `fast_flights` TypeError** (61 occurrences since 2026-08-03,
  pre-existing, unrelated) confounded 017's 6.3/6.4 and will confound Step 5
  the same way. Worth fixing first as its own small task.
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
