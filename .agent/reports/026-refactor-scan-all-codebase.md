# Refactor Scan — all codebase

**Target:** `/srv/airfare-monitor` (all of it) · **Date:** 2026-08-15
**Verdicts:** 4 ✅, 7 🕐, 1 ⚠️, 3 ❌ · **Touch uncovered code:** 3
**Method:** full read of `backend/` (15 files), `frontend/static/`, `scripts/`, `tests/` inventory; git history hotspot analysis (last 100 commits: `kayak.py` 28, `pages.py` 18, `test_kayak_source.py` 15).

**Behavior-preservation contract:** A refactor must not change observable behavior; proof is existing tests green before and after. Where affected code is uncovered, characterization tests (`/add-tests`) must be written and passing FIRST. Verdicts below factor that prerequisite in.

---

## 1. ✅ Three strip functions in `kayak.py` are one algorithm copied three times

- **What:** `_strip_placements` (kayak.py:382), `_strip_nearby_airport_promos` (kayak.py:351), `_strip_self_transfer_rows` (kayak.py:315) — each ~30 lines implementing the identical block-scan: walk lines → find start-marker line → scan to end-marker within a `_MAX_BLOCK_LINES` bound → if no terminator in range, drop only the start line. Only the markers and bounds differ.
- **Why it matters:** `kayak.py` is the hottest file in the repo (28 commits / 100) and these three grew by accretion — each new phantom-price class (plan 020, off-route, self-transfer) added another copy. A fourth copy is likely (TODO's own "assume there is a fourth" guard-class note). Skyscanner (roadmap) will need the same *shape* re-derived; a named generic makes that a parameter choice, not a re-read.
- **Proposed refactor:** one pure `_strip_blocks(body_text, start_pred, end_pred, max_lines)` in `kayak.py`; each strip becomes a thin wrapper binding its markers. Keep each wrapper's semantics exactly (placement end-search starts after the disclosure line; self-transfer ends at `_RESULT_MARKERS_LOWER`).
- **Effort:** S–M, 2–4h. Riskiest part: off-by-one block bounds — mitigated by existing boundary tests.
- **Blast radius:** 1 file + 3 test files (unchanged — they pin behavior).
- **Coverage:** covered (`test_kayak_placements.py`, `test_kayak_offroute_prices.py`, `test_kayak_source.py`).
- **Verdict:** ✅ worth it now.

## 2. 🕐 `_build_detail_context` is a 315-line god function (pages.py:476–791)

- **What:** one async function performing seven jobs: per-source observation blending (492–528), delta computation (551–567), missing-row reconstruction (577–588), sticky-key/history merging (613–643), chart color assignment (649–681), airline facet building (722–744), sparklines + freshness (757–772) — with two nested closures (`_flight_label`, `_label_for_key`).
- **Why it matters:** it's the single point every detail-page feature flows through, and the roadmap (Skyscanner expandable row view, per-source breakdown, "extending `_group_duplicate_price_rows`") all land here. Tests for it are page-level (5 test files, ~1,300 lines) so a change re-runs whole-page assertions, not unit checks.
- **Proposed refactor:** extract the middle chunk into module-level pure functions taking `(observations, rows, tracker, top_n, sticky_keys)` and returning context fragments — e.g. `_blend_observations()`, `_compute_deltas()`, `_build_history_by_key()`, `_build_airline_facets()`. Keep `_build_detail_context` as a short orchestrator. No behavior change.
- **Effort:** M–L, 6–10h. Riskiest: preserving the ORDER of steps (several are ordering-coupled, e.g. history merge's `_last_snapshot_for_key`).
- **Blast radius:** 1 function, ~6 test files as the safety net (unchanged).
- **Coverage:** covered (page-level).
- **Verdict:** 🕐 worth it eventually — do it as the opening move of the Skyscanner/expandable-row phase, not standalone.
- **Trigger:** Skyscanner or expandable-row work starts; or `_build_detail_context` changes 3+ more times.

## 3. 🕐 `kayak.py` generic machinery vs page heuristics — rename-before-Skyscanner seam

- **What:** `kayak.py` (1080 lines) mixes four concerns: page-text heuristics (`_strip_*`, `_results_section`, `_page_currency`, `_*_grounded`), browser config (`KayakRenderConfig`, `_launch_args`, `_context_options`, `_warmup_sequence`, `_WorkerProcess`, `_spawn_render_worker`), LLM extraction, and the `SearchSource` adapter. `kayak_render.py` imports its config/constants **from** `kayak.py` (kayak_render.py:26–36), so the "generic" render worker is entangled with Kayak-specific text.
- **Why it matters:** TODO.md already decided the plan — Skyscanner "uses the Kayak render+extract strategy" and the generic machinery (`kayak_render.py`, `kayak_samples.py`, the `posix_spawn` seam, the evasion bundle) must be "renamed rather than duplicated". Doing it now, with only one consumer, is cheaper than untangling after a second source exists.
- **Proposed refactor:** split into `backend/browser_render.py` (worker contract + spawn seam), `backend/render_samples.py` (capture), and a small config-contract module for `KayakRenderConfig`/timeouts/`_RESULT_MARKERS`-independent constants — so `kayak_render.py` stops importing the Kayak-specific module. Heuristics stay in `kayak.py`.
- **Effort:** M, 4–8h. Riskiest: `test_kayak_timeout_budget.py` **reads `kayak_render.py`'s source** to pin timeout invariants — moving lines breaks the test unless the test's target paths are updated in the same change.
- **Blast radius:** ~5 backend files, ~6 test files (some asserting import paths).
- **Coverage:** covered.
- **Verdict:** 🕐 — real value but zero user-visible payoff until Skyscanner; sequence it as Skyscanner's phase 0.
- **Trigger:** Skyscanner implementation approved.

## 4. ✅ Benchmark script's copied prompt + drifted `_time_grounded` (scripts/kayak_model_benchmark.py:59–133)

- **What:** `_user_message` (line 59) is a byte-for-byte copy of the user message `_extract` builds inline (kayak.py:792–797), kept duplicated because "this phase may not refactor kayak.py" — that constraint has expired. Worse: the benchmark's `_time_grounded` (line 116) is an **older** copy of `KayakSource._time_grounded` that has already drifted — production gained the 24h-locale fallback and the unparseable-keeps rule; the benchmark still 12-hour-only and returns `False` for unparseable. The benchmark silently measures a different correctness rule than production.
- **Why it matters:** this script is the project's model-selection safety net (used again 2026-08-15 for the Go migration). A benchmark that scores by the wrong rule will pick the wrong model — the exact failure class it exists to prevent.
- **Proposed refactor:** add `_build_extraction_user_message(body_text, top_n, depart_date)` (module-level, pure) to `kayak.py`; `_extract` uses it; the benchmark imports it. Import `KayakSource._time_grounded` into the benchmark instead of its local copy (its callers adapt — they already unpack production-shaped results).
- **Effort:** S, 1–2h. Riskiest: nothing — behavior identical by construction.
- **Blast radius:** 2 files (`kayak.py`, benchmark); benchmark has **no tests** (uncovered) — add a small characterization test pinning the message as a prerequisite.
- **Coverage:** target of the extraction (`kayak.py`) covered; benchmark uncovered.
- **Verdict:** ✅ worth it now — cheapest fix on the list that removes a *currently-real* drift.

## 5. 🕐 Chart palette triplicated across server and two JS files

- **What:** `CHART_COLORS` in pages.py:34–37, `COLORS` in filters.js:2–5, `colors` in charts.js:1–4 — the identical 10-color palette in three places, one of them (charts.js) only used as a fallback.
- **Why it matters:** a palette change needs 3 coordinated edits; if one drifts, table-row accents disagree with chart lines with no error. The color-RANK rule is already shared by convention (documented in CLAUDE.md); the palette itself should be a single fact.
- **Proposed refactor:** server remains source of truth — pages.py emits the palette into the page context (e.g. `window.CHART_COLORS` JSON in `base.html`); both JS files read it, with a local copy kept only as a last-resort fallback.
- **Effort:** S, 1–2h + manual browser verification (no JS test runner exists).
- **Blast radius:** 3 files; `test_chart_colors.py` pins the Python side and stays green.
- **Coverage:** Python side covered; **JS side uncovered** — verification is manual.
- **Verdict:** 🕐 — cheap but no safety net and near-zero churn rate.
- **Trigger:** any chart/theme work, or a palette edit.

## 6. ✅ `search_and_store`'s `delay=True` default footgun + duplicated error blocks (scheduler.py)

- **What:** (a) `search_and_store(tracker_id, delay: bool = True)` — the default has already bitten: two call sites forgot `delay=False` and blocked their HTTP responses up to 15 min (fixed in 024 Phase 1). The APScheduler job also relies on the default implicitly. (b) Two near-identical "read last_error via getattr → insert_log" blocks (lines 95–103 and 130–138) differing only in event name.
- **Why it matters:** a default that silently sleeps 0–15 min is a trap for every future call site; the duplication of the error channel doubles the chance the observability contract (which TODO lists as a defect class) is broken on one path.
- **Proposed refactor:** remove the `delay` default (callers must choose; the job registration passes `delay=True` explicitly via `args=[tracker_id, True]`); extract `_log_source_error(event, source, tracker_id)` for the two blocks.
- **Effort:** S, ~1h. Riskiest: the job-registration arg change (one line).
- **Blast radius:** scheduler.py + 5 existing call sites already pass `delay` explicitly; `test_kayak_scheduling.py` covers the paths.
- **Coverage:** covered.
- **Verdict:** ✅ worth it now.

## 7. ✅ `FlightResult` field list hand-copied into a dict literal (scheduler.py:152–168)

- **What:** the `prices` list re-spells all 14 `FlightResult` fields by name, mirroring `backend/sources/base.py:5–17`.
- **Why it matters:** Passengers (next queued feature, TODO) will very likely add fields to `FlightResult` (per-person price, passenger count) — this literal silently drops any new field from the DB row with no error.
- **Proposed refactor:** `{**dataclasses.asdict(r), "flight_key": make_flight_key(r)}` — or a `flight_result_to_row(r)` helper next to `FlightResult` so the field list lives once.
- **Effort:** S, 30–60 min.
- **Blast radius:** 1 function; `insert_flight_prices` untouched.
- **Coverage:** covered (`test_kayak_scheduling.py`, `test_db.py`).
- **Verdict:** ✅ worth it now — before Passengers lands.

## 8. 🕐 Tracker lifecycle wiring duplicated across two routers (pages.py + api.py)

- **What:** "activate/pause" is implemented four times: `toggle_tracker` (pages.py:452), `toggle_tracker_detail` (pages.py:824, near-identical body), `update_tracker_endpoint`'s active branch (api.py:64–68); "create + log + search + schedule" twice: `add_tracker` (pages.py:427) and `create_tracker_endpoint` (api.py:37).
- **Why it matters:** each new lifecycle side effect (log line, job wiring, future `tracker_sources` row) must be remembered in 4–6 places; Passengers adds tracker columns and will touch exactly these flows.
- **Proposed refactor:** a thin `backend/tracker_service.py` with `create_tracker_wired(...)` and `set_tracker_active(tracker_id, active)`; both routers call it. Routes stay as-is (rendering differences remain in the routers).
- **Effort:** M, 3–6h. Riskiest: the two toggle routes render different partials — keep rendering in the routes.
- **Blast radius:** 2 files + tests unchanged (page-level).
- **Coverage:** covered.
- **Verdict:** 🕐 — real duplication, but both flows work and are tested; no immediate pain.
- **Trigger:** Passengers lands a tracker mutation, or a third toggle appears.

## 9. ⚠️ `last_error`/`last_error_level` observability channel is convention, not contract

- **What:** sources signal degradation via two mutable attributes read with `getattr(source, "last_error", None)` / `getattr(..., "last_error_level", "ERROR")` (scheduler.py:95–97, 130–132); `FallbackSource` manually merges child errors (fallback.py:41–54). `SearchSource` protocol declares only `search() -> list[FlightResult]`.
- **Why it matters:** TODO names this the recurring defect class — "held by convention, not by construction" (it produced the FallbackSource silent-degradation bug). Every new source must learn the convention; nothing fails when it's forgotten.
- **Proposed refactor:** `search()` returns a `SearchOutcome(rows, error, level)` (or protocol gains an `outcome` property). Sources and scheduler updated together; `FlightResult` list stays for rows.
- **Effort:** L, 8–12h. Riskiest: touching every source + `FallbackSource`'s error-merging semantics.
- **Blast radius:** 4 source files, scheduler, ~10 test files asserting `last_error` directly.
- **Coverage:** covered, but the tests *pin the current shape* — they'd all need mechanical adaptation.
- **Verdict:** ⚠️ risky — real value, widest blast radius on this list. Defer unless forced.
- **Trigger:** implementing a Skyscanner source (a new source is when the convention must be re-learned); do it then, as part of that feature.

## 10. 🕐 db.py: ~20 copies of connection boilerplate + inconsistent `PRAGMA foreign_keys`

- **What:** every function in db.py opens `aiosqlite.connect(get_db_path())`, sets `row_factory`, and *sometimes* sets `PRAGMA foreign_keys=ON` (create_tracker, delete_tracker, create_snapshot, insert_flight_prices, create_notification, insert_notification_log — but not delete_notification, list_notifications, …).
- **Why it matters:** the next function added to db.py (Passengers columns, DB-size side tables) copies whichever variant it was written after; the PRAGMA inconsistency is a real but currently-dormant correctness difference.
- **Proposed refactor:** a module-level `_connect()` async context manager (connection + row_factory + PRAGMA), each function a 3-line body around its SQL.
- **Effort:** M, 3–5h, fully mechanical.
- **Blast radius:** 1 file; every db test exercises it.
- **Coverage:** covered.
- **Verdict:** 🕐 — wide-but-safe diff with mostly hygiene payoff; bundle it with the next db.py change (the DB-size normalization work) rather than standalone.

## 11. ❌ Timestamp-parsing duplicated: `_parse_ts` (pages.py:43) vs `_snapshot_age_minutes` (main.py:67)

- **What:** same two-format loop, same `split(".")[0]` handling, in two modules.
- **Why it matters:** barely anything — a third copy would tip it.
- **Proposed refactor:** one helper in a shared module.
- **Effort:** S. **Verdict:** ❌ not worth a cross-module churn for 8 lines — consolidate opportunistically if either file is touched anyway.

## 12. 🕐 Per-source opt-in as tracker column pairs (`kayak_enabled`, `kayak_next_due_at`)

- **What:** trackers table carries one source's cadence as columns; `search_and_store` hardcodes the Kayak block; `_get_kayak_render_lock` is Kayak-named.
- **Why it matters:** TODO already decided: Skyscanner would double the column pairs and the scheduler block; "move to a `tracker_sources` table (tracker_id, source, enabled, next_due_at) before adding the second pair, not after."
- **Proposed refactor:** `tracker_sources` table + scheduler iterating enabled sources. Schema migration = confirmation-gated.
- **Effort:** L, 8–12h as part of Skyscanner. **Coverage:** covered.
- **Verdict:** 🕐 — planned; no user-visible payoff until the second source exists.
- **Trigger:** Skyscanner implementation approved.

## 13. ❌ `models.py` hardcoded defaults duplicate `DEFAULT_INTERVAL_MINUTES` (db.py)

- **What:** `TrackerCreate.interval_minutes: int = 60`, `top_n: int = 5` re-state constants declared "single source of truth" in db.py.
- **Verdict:** ❌ — the "matches db.py" note is already the mitigation; only revisit if defaults change (then the change is a 3-site edit either way).

## 14. 🕐 `_relative_minutes` (pages.py:215) mirrors `updateRelativeTimes()` bucketing (base.html:15)

- **What:** the mins→hours→days thresholds exist in Python and JS, kept in sync by comment + a Python-side boundary test.
- **Why it matters:** drift shows as "66m ago" next to "1h ago". The JS side is unpinned — only the Python side has a test.
- **Proposed refactor:** ship bucketing thresholds as data (`data-*` attrs) so JS reads them; or accept the pinned-by-comment state.
- **Effort:** S–M. **Coverage:** Python covered; JS uncovered.
- **Verdict:** 🕐 — low value, low urgency; the test at least pins one side.

## 15. ❌ `flight_key` dedupe/identity sites — deliberately leave alone

- **What:** seven-plus dedupe sites (`_dedupe_rows`, `_group_duplicate_price_rows`, blend logic, history merge, …) each with deliberately different rules (results table is the documented exception).
- **Verdict:** ❌ do not consolidate. This was just audited (plans 024/025, TODO). The differences are product decisions, not accidents; merging them would re-introduce the exact bugs those plans fixed. CLAUDE.md notes ARE the documentation.

---

## Top 3 by value/effort

1. **#7 — `FlightResult` → `asdict` in scheduler** (S, 1h): closes a silent field-drop trap immediately before Passengers adds fields.
2. **#4 — benchmark prompt/`_time_grounded` dedup** (S, 1–2h): removes the only duplication on this list that has *already drifted*, in the script that picks production models.
3. **#1 — strip-block algorithm consolidation in kayak.py** (S–M, 2–4h): shrinks the hottest file and gives the next phantom-price class a ready-made shape. (#6 is an honorable fourth — same size, less value.)

## Explicitly do NOT refactor

- **#15 — the `flight_key` dedupe/identity sites.** Freshly audited and deliberate; consolidation risk exceeds value.
- **`fingerprint.py`.** Landed 2 days ago (plan 025) with a verified key-preserving migration; let it settle.
- **The Kayak timeout constants** (`_WORKER_TIMEOUT_S` derivation). A test pins them by reading source — reorganizing them breaks the guard unless re-derived in the same commit. Only touch with the timeout-budget test in the loop.

## Architectural observation

The biggest un-managed structural risk isn't a god function — it's **~500 lines of client-side logic with zero execution-based tests holding three documented cross-file invariants** (palette identity, relative-time bucketing, color rank + sticky-missing fallback). The server has built a strong "pin the invariant with a test" discipline (timeout budget, dedupe identity); the frontend has none of it — no JS runner exists at all, so every JS refactor's "safety net" is manual browser checking. Before the Skyscanner/expandable-row UI work (which will grow `filters.js`), adding a minimal JS test harness (node + jsdom, or Playwright) would buy more protection than any single extraction above. All three "touches uncovered code" verdicts above are JS-side for exactly this reason.
