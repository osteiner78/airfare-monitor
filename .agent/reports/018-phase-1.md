# Plan 018 — Phase 1: config seam + fingerprint construction

## What I built

- `KayakRenderConfig` dataclass (`backend/sources/kayak.py`) holding the full
  C1–C4 bundle as a parameter object: `headless`, `user_data_dir`, `locale`,
  `timezone_id`, `viewport`, `warmup_url`, `warmup_dwell_s`, `stealth`.
  Defaults are the shipped bundle — headful (`headless=False`, C2), a
  persistent profile under `data/kayak-profile` (C3), English `kayak.com`
  warm-up (task 1.8), `timezone_id="America/Sao_Paulo"` (deliberate, tracks
  current egress geography per task 1.8), `stealth=True` (C4).
- Pure helpers, all module-level so they match the test imports:
  `_launch_args` (adds `--disable-blink-features=AutomationControlled`,
  never `--enable-automation`), `_derive_user_agent`/`_context_options`
  (strips the `HeadlessChrome` token from a supplied default UA string
  rather than hardcoding one), `_fingerprint_is_consistent` (checks UA has
  no Headless/Playwright token, `timezone_id` is set, viewport is a
  plausible desktop size — deliberately does **not** require locale/timezone
  region agreement, per task 1.8's decision that language and physical
  location are independent), `_warmup_sequence` (returns pre-search
  `[(url, dwell)]`, empty when `warmup_url` is unset, dwell sampled from
  `warmup_dwell_s` via `random.uniform`), `_simulate_interaction` (mouse
  move + wheel scroll before reading the DOM).
- `_RESULT_MARKERS = {"Select", "Selecionar", "Auswählen"}` (task 1.10),
  used by `_wait_for_results_stable` (polls all markers, sums counts)
  instead of the hardcoded `"Select"` string.
- `_price_grounded` (task 1.9) now also accepts dot-thousands (`"4.312"`)
  and dot-thousands-with-comma-decimals (`"4.312,00"`) alongside the
  existing plain and comma-thousands forms, so a redirect to a non-English
  Kayak locale can't silently drop every four-digit fare as "hallucinated."
- `KayakSource.__init__` now takes an optional `config: KayakRenderConfig
  | None`, defaulting to `KayakRenderConfig()`.
- `_render` rewritten to use the config: a cheap throwaway headless launch
  first reads the real default `navigator.userAgent` (Decision 4 — derive,
  never hardcode), then the real context is built via
  `launch_persistent_context` (when `user_data_dir` is set) or
  `launch()` + `new_context()`, with the derived locale/timezone/viewport/UA
  applied. Before the search URL, `_warmup_sequence` steps are visited and
  dwelt on; before reading the body, `_simulate_interaction` runs.

## Verification output

`pytest tests/test_kayak_render_config.py -v` (run inside the container,
which already has `requirements-dev.txt` installed — the host has neither
`pytest-asyncio` nor Docker network access to the venv):

```
collected 17 items

tests/test_kayak_render_config.py::test_launch_args_disable_automation_controlled_blink_feature PASSED
tests/test_kayak_render_config.py::test_launch_args_do_not_enable_automation PASSED
tests/test_kayak_render_config.py::test_context_options_derive_user_agent_from_browser_version PASSED
tests/test_kayak_render_config.py::test_derived_user_agent_strips_headless_token PASSED
tests/test_kayak_render_config.py::test_fingerprint_consistent_for_default_config PASSED
tests/test_kayak_render_config.py::test_fingerprint_inconsistent_when_user_agent_says_headless PASSED
tests/test_kayak_render_config.py::test_fingerprint_allows_english_locale_with_a_non_english_timezone PASSED
tests/test_kayak_render_config.py::test_fingerprint_inconsistent_when_timezone_is_missing PASSED
tests/test_kayak_render_config.py::test_fingerprint_inconsistent_for_headless_default_viewport PASSED
tests/test_kayak_render_config.py::test_warmup_sequence_visits_homepage_before_search_url PASSED
tests/test_kayak_render_config.py::test_warmup_sequence_empty_when_warmup_url_not_set PASSED
tests/test_kayak_render_config.py::test_warmup_dwell_is_not_always_the_same_value PASSED
tests/test_kayak_render_config.py::test_simulate_interaction_emits_mouse_and_scroll_events PASSED
tests/test_kayak_render_config.py::test_result_markers_include_english_and_localized_variants PASSED
tests/test_kayak_render_config.py::test_config_defaults_to_the_c1_c4_bundle PASSED
tests/test_kayak_render_config.py::test_kayak_source_accepts_a_render_config PASSED
tests/test_kayak_render_config.py::test_kayak_source_defaults_to_the_bundle_config PASSED

============================== 17 passed in 0.09s ==============================
```

`pytest tests/test_kayak_source.py -v -k "dot_thousands or comma_decimals"`
(the two task-1.9 additions):

```
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_uses_dot_thousands_separator PASSED
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_uses_comma_decimals PASSED

======================= 2 passed, 29 deselected in 0.08s =======================
```

`pytest tests/ -v -k "not slow"` (full suite):

```
=================================== FAILURES ===================================
FAILED tests/test_kayak_samples.py::test_structural_signal_flags_short_page_with_no_select_occurrences
FAILED tests/test_kayak_samples.py::test_structural_signal_does_not_flag_long_results_page
FAILED tests/test_kayak_samples.py::test_structural_signal_does_not_flag_long_page_that_merely_lacks_markers
FAILED tests/test_kayak_samples.py::test_structural_signal_recognises_localized_action_buttons
FAILED tests/test_kayak_samples.py::test_sample_capture_writes_body_and_sidecar
FAILED tests/test_kayak_samples.py::test_sample_sidecar_records_config_id_and_blocked_verdict
FAILED tests/test_kayak_samples.py::test_sample_capture_survives_unwritable_directory
FAILED tests/test_kayak_samples.py::test_two_samples_in_the_same_second_do_not_overwrite_each_other
================= 8 failed, 319 passed, 3 deselected in 23.33s =================
```

The 8 failures are all `tests/test_kayak_samples.py` — Phase 2 deliverables
(`_looks_blocked_structurally`, `backend.kayak_samples.capture_sample`),
untouched by design ("What NOT to touch" — this phase changes how the page
is fetched, nothing downstream, and the sample harness is explicitly Phase
2 scope). 300 → 319 passed is +19 (17 render-config tests + 2 price-
grounding tests), matching the pre-existing baseline plus this phase's new
green tests exactly.

## Operational check (Active dev, per this session's instructions)

`backend/` edits deploy live instantly to the 6-tracker production service.
I made no Dockerfile/compose changes (that's Phase 2), so no rebuild was
needed, but the code change was live the moment it saved.

**Risk noticed and worked around:** the new default config sets
`headless=False` (C2) and `user_data_dir` (C3) — both real behavior changes
to `_render`, and tracker 20 has `kayak_enabled=1`. Headful Chromium needs
an X display; Phase 2 (not yet landed) is what adds Xvfb to the container.
The orchestrator's brief for this session was explicit that live Kayak
requests are out of scope until Phase 3, so rather than run
`search_and_store` against tracker 20, I ran it against tracker 21
(`active=1`, `kayak_enabled=0`) to verify the main collection path without
touching Kayak at all:

```
$ docker compose ps
NAME              STATUS
airfare-monitor   Up 10 hours (healthy)

$ docker exec airfare-monitor python -c "
import asyncio
from backend.scheduler import search_and_store
asyncio.run(search_and_store(21, delay=False))
print('search_and_store(21) completed without raising')
"
search_and_store(21) completed without raising
```

`system_logs` confirms a clean `search_start` → `search_done` (`6 results`)
pair for tracker 21, and `docker compose ps` still shows the container
`healthy` afterward.

**Left as-is, flagged for awareness:** tracker 20's *next* natural Kayak
attempt (its `kayak_next_due_at` was `2026-08-05 06:26:48` at last check)
will run with `headless=False` against a container with no Xvfb yet. This
will fail — `KayakSource.search()`'s existing try/except degrades that to
zero rows plus a logged `kayak_search_error`, exactly like every other
Kayak failure to date, so it does not break the shared snapshot or the
other 5 trackers' collection. It is a real behavior change from Phase 1
landing before Phase 2, worth being aware of if checking `/monitor` before
Phase 2 ships, but not a regression relative to Kayak's current 0-for-5
track record.

## Commit

`5eb1b41` — `[phase-1.1-1.10] Turn Kayak's evasion stack into a config seam`

## Deviations from the plan

- `.gitignore`: the plan's Files section for both 1.1 and 2.x lists
  `.gitignore` as modified, for the profile-dir gitignore requirement
  (task 1.5). `data/` is already gitignored wholesale (pre-existing
  `.gitignore` line), which covers `data/kayak-profile` — no edit needed
  now. Left `.gitignore` untouched.
- `_render`'s exact mechanics (throwaway probe launch to read the real
  default UA, then a second real launch/context with derived options) are
  not pinned by any test — Phase 1's tests are all offline/pure per the
  plan's own framing ("Out of scope: any live Kayak request"). I implemented
  it to match the plan's stated intent (1.5–1.7) and Decision 4 as closely
  as I could reason through, but it is unverified against a real browser
  until Phase 3's Step 1 (or the Phase 2 Xvfb smoke check).

## Test gaps

None. All 19 of this phase's tests were pre-written; none needed
authoring, none were touched.

## Follow-ups (noted, not done — out of this phase's scope)

- `_wait_for_results_stable` now polls `_RESULT_MARKERS` (three markers)
  every second rather than one — three `page.get_by_text(...).count()`
  calls per poll instead of one. Not a concern for a 45s cap, but worth
  knowing if render latency is ever profiled.
- Tracker 20's `headless=False` exposure until Phase 2 lands (see above) —
  not a code change, just a live-service timing note.

## Confidence rating

**likely-good.** The 19 pure/offline tests this phase owns pass, the full
suite shows no regressions, and the live `search_and_store` smoke check
confirms the main collection path is unaffected. The one area I can't rate
higher than "likely" is `_render`'s actual runtime behavior against a real
browser (probe-launch UA derivation, `launch_persistent_context` argument
shape, warm-up navigation) — none of that is exercised by Phase 1's
tests-by-design, and won't be until Phase 2's Xvfb smoke check or Phase 3.
