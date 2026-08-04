# Plan 017 — Phase 2 report: `backend/sources/kayak.py` (Playwright render + LLM extraction)

## What was built

A self-contained `KayakSource` implementing `SearchSource`, structured as the
four swappable seams the plan specified:

- `_build_url(origin, dest, depart_date, currency)` (pure, static) — builds
  `https://www.kayak.com/flights/{origin}-{dest}/{depart_date}?sort=price_a&currency={currency}`.
- `_looks_blocked(body_text)` (pure, static) — substring-checks a marker list
  (`verify you are human`, `unusual traffic`, `are you a robot`, `captcha`,
  `access denied`, `automated queries`) against the lowercased body text.
- `_render(url)` (async, Playwright boundary) — launches headless Chromium via
  `async_playwright()`, navigates, polls the count of `"Select"` button text
  until it stabilizes for two consecutive 1s polls (capped at 45s via
  `_wait_for_results_stable`), returns `page.inner_text("body")`.
  `try/finally browser.close()` inside the `async with` block per 2.5's
  lifecycle note.
- `_extract(body_text, top_n)` (async, LLM boundary) — calls an
  OpenAI-compatible client (`AsyncOpenAI`, DeepSeek's `base_url`) with a JSON
  structured-output request, reads the API key from `os.environ["DEEPSEEK_API_KEY"]`
  **at call time** (2.11), raises naturally (`KeyError`/`json.JSONDecodeError`)
  on a malformed response rather than swallowing it (2.6).
- `_validate(rows, body_text)` (pure, static) — the grounding check (2.7):
  drops rows whose price isn't literally present in `body_text` in either
  bare-integer or comma-thousands-separated form, drops non-positive prices,
  then drops prices more than 10x the median of the surviving set. Logs a
  `WARNING` (via `logging.getLogger(__name__)`, this module's own logger —
  nothing like it existed elsewhere in the codebase to reuse) naming each
  dropped row.
- `search()` wires these together in the order the plan specifies: short-circuit
  on `top_n <= 0` before rendering → build URL → `_render` → `_looks_blocked`
  (blocked ⇒ `WARNING`, return `[]` without calling `_extract`) → `_extract` →
  (`[]` result ⇒ `WARNING`, legitimate no-flights state) → `_validate` → map to
  `FlightResult` with `source="kayak"` and the request's `currency` (not
  re-parsed from the page). The whole body runs under
  `asyncio.wait_for(..., timeout=90s)` (2.8's overall wall-clock cap). Any
  exception (from render, extraction, or a timeout) is caught once at the
  `search()` level, scrubs the live `DEEPSEEK_API_KEY` value out of the error
  string before it reaches `last_error` (2.9), and sets `last_error_level = "ERROR"`.
  `booking_url` is the constructed Kayak search URL itself (2.8, same
  precedent as `fast_flights.py`).
- `_map_result` defaults `duration_min`/`stops` to `None` via `.get()` rather
  than raising `KeyError` on a response missing optional fields (2.10).

`requirements.txt`: added `playwright==1.62.0` (exact pin — 2.1's rationale:
the browser binary lives outside the `.:/app` mount, so an unpinned bump could
silently mismatch the installed browser revision) and `openai>=1.0` (the
OpenAI-compatible client library for DeepSeek's API).

## Verification output

```
pytest tests/test_kayak_source.py -v -k "not slow"
============================= test session starts ==============================
collected 24 items / 1 deselected / 23 selected

tests/test_kayak_source.py::test_kayak_source_satisfies_search_source_protocol PASSED
tests/test_kayak_source.py::test_build_url_includes_origin_destination_and_date PASSED
tests/test_kayak_source.py::test_build_url_sorts_by_cheapest_price PASSED
tests/test_kayak_source.py::test_build_url_encodes_requested_currency PASSED
tests/test_kayak_source.py::test_looks_blocked_true_when_captcha_marker_present PASSED
tests/test_kayak_source.py::test_looks_blocked_false_for_normal_results_page PASSED
tests/test_kayak_source.py::test_looks_blocked_false_for_empty_string PASSED
tests/test_kayak_source.py::test_search_returns_flight_results_mapped_from_extraction PASSED
tests/test_kayak_source.py::test_search_sets_source_field_to_kayak_on_every_result PASSED
tests/test_kayak_source.py::test_search_result_currency_matches_requested_currency PASSED
tests/test_kayak_source.py::test_search_returns_empty_list_and_error_when_render_raises PASSED
tests/test_kayak_source.py::test_search_returns_empty_list_and_warning_when_blocked_markers_detected PASSED
tests/test_kayak_source.py::test_search_returns_empty_list_and_error_when_extraction_raises PASSED
tests/test_kayak_source.py::test_search_returns_empty_list_and_warning_when_extraction_finds_no_flights PASSED
tests/test_kayak_source.py::test_search_with_top_n_zero_returns_empty_list_without_rendering PASSED
tests/test_kayak_source.py::test_search_never_raises_for_unexpected_exception_type PASSED
tests/test_kayak_source.py::test_search_maps_result_with_missing_optional_fields_without_crashing PASSED
tests/test_kayak_source.py::test_validate_drops_row_whose_price_is_absent_from_body_text PASSED
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_appears_thousands_separated PASSED
tests/test_kayak_source.py::test_validate_drops_non_positive_price PASSED
tests/test_kayak_source.py::test_validate_drops_price_wildly_outside_the_band_of_other_rows PASSED
tests/test_kayak_source.py::test_search_drops_hallucinated_price_not_present_in_rendered_text PASSED
tests/test_kayak_source.py::test_error_message_does_not_contain_api_key PASSED
======================= 23 passed, 1 deselected in 0.23s =======================
```

The `slow` test (`test_real_kayak_search_returns_results_for_valid_route`)
collects correctly but was **not run** — it needs a real `DEEPSEEK_API_KEY`,
network access, and a working Chromium install, none of which are present in
this dev container yet (Chromium/Playwright browser binaries land outside the
bind mount and aren't installed until Phase 5's `playwright install --with-deps
chromium`). Deferred to Phase 6 per the plan's own scoping.

```
pytest tests/ -v -k "not slow"
================ 25 failed, 258 passed, 3 deselected in 34.40s =================
```
All 25 remaining failures are confined to `test_best_source.py` (6, Phase 4)
and `test_kayak_scheduling.py` (19, Phase 3 — including the `kayak_enabled`
schema column that Phase 3.1 adds). 258 passed = the 235 baseline after Phase
1 + all 23 newly-green Phase 2 tests. No regressions.

Note: `_render`/`_extract`'s real bodies import `playwright`/`openai` lazily
(inside the method, not at module load) — every mocked test patches
`_render`/`_extract` directly via `patch.object`, so the real bodies (and
their imports) are never executed. All 23 non-slow tests pass in this
container **without** `playwright`/`openai` installed. They're only needed
for the deferred `slow` test and for the real container build in Phase 5.

## Commit hash(es)

See below — committed after this report, message
`[phase-2.1-2.11] backend/sources/kayak.py`.

## Deviations from the plan

- **Model ID unverified (Decision 6 / 2.6 open question).** Used
  `deepseek-chat` as `_LLM_MODEL` — a placeholder, flagged with a `TODO`
  comment in the code. The plan explicitly states this "must be confirmed
  against the provider's live model list at implementation time" and that v1
  wrongly stated it as settled fact. I have no network access to verify
  DeepSeek's current model list or structured-output support from this
  session, and no test asserts a specific model string (every test mocks
  `_extract` directly), so this doesn't block any Phase 2 test — but it
  **must** be confirmed before Phase 6's live run, or swapped for the
  Claude Haiku 4.5 alternative Decision 6 names.
- **Kayak currency/locale URL parameter (2.3 open question).** Used
  `?sort=price_a&currency={currency}` — matches what the hand prototype is
  described as using and satisfies the tests (`"EUR" in url_eur`), but 2.3
  flags this as unverified for the real param name against a non-USD tracker.
  Not verifiable without a live request from this session; flagged for Phase 6.
- **`_looks_blocked` marker list** is the starting set the plan itself
  describes as necessarily incomplete ("expand from real logs; that's
  maintenance, not a defect") — not a deviation, just noting it per the
  plan's own risk callout.
- Used Python's standard `logging` module for `_validate`'s dropped-row
  warnings (2.7) since nothing in this codebase's other source files uses a
  logger — they only set `last_error`/`last_error_level`. `_validate` is a
  pure static function with no instance state, so it can't populate
  `last_error`; stdlib `logging` was the smallest addition that satisfies
  "log a WARNING naming each dropped row" without inventing new plumbing.

## Test gaps flagged / new tests added

None. All orchestrator-written tests for this phase passed as written; no
gaps found, no new tests added.

## Follow-ups / noted-but-not-done

- Confirm the DeepSeek model ID (or switch to Claude Haiku 4.5) and the
  Kayak currency URL param against live traffic before Phase 6.
- `_extract`'s JSON-schema strictness (raise-on-malformed) has not been
  exercised against a real DeepSeek response shape yet — only against the
  mocked `AsyncMock` return values in this phase's tests.

## Confidence rating

**Likely-good.** All plan-mandated non-slow tests pass, full suite shows zero
regressions, and the code follows the plan's four-seam structure and every
numbered task (2.1–2.11) exactly. Confidence is capped at "likely-good" rather
than "certain" because the two explicitly-flagged open questions (model ID,
currency param) are real unknowns this session couldn't verify against live
Kayak/DeepSeek traffic — by the plan's own design, that verification is
Phase 6's job, not Phase 2's.
