# 024 — Code review consolidation + remediation plan

**Inputs:** `.agent/reports/022-code-review.md` (Opus + DeepSeek v4 Pro, the
latter completing the former's pass), `.agent/reports/023-code-review-cross-file-invariants.md`
(Qwen 3.8 Max, independent).
**Date:** 2026-08-13
**Orchestrator verification:** every finding below was re-checked against the
working tree and the production DB before being accepted. Two claims did not
survive that check — see "Corrections to the source reports".

The two reviews were run independently and converge on the same top three.
That agreement is worth something, but it is not proof: both models read the
same code and can make the same reading error, and one of them did.

---

## Corrections to the source reports

**1. `022` F1 overstates the airline fork.** It offers two evidence rows; only
one forks.

```
Tap Air Portugal (google/fast_flights)  ->  flight_key "tap air portugal|..."
TAP AIR PORTUGAL (kayak)                ->  flight_key "tap air portugal|..."
```

`_normalize_airline` casefolds, so these already share a key — verified across
every TAP row at `2026-08-21T20:45:00`. `023` classifies TAP correctly as
bridged. The finding stands on `LATAM`/`LATAM Airlines` and `ITA`/`ITA
Airways`, which do fork; the TAP row should not be counted in its scope.

**2. `022` N3 names one API call site; there are two.** `023` A3 is right:
`api.py:42` (`POST /api/trackers`) has the same omission as `api.py:106`.
Confirmed by grep. It is inert today only because `TrackerCreate` cannot set
`kayak_enabled`, which makes it a latent duplicate of the same bug rather than
a non-issue.

**3. `023`'s A1 evidence table has a typo** (`2826-08-21`). Cosmetic; the
underlying rows are real — I reproduced them with my own query.

**4. Process finding, from `022` itself, that both reports underweight.** An
earlier review pass wrote production code mid-review — `_rebase_departure_date`,
the airline facet grouping, and `_relative_minutes` are all *uncommitted
working-tree changes authored during a review that was explicitly scoped
"findings get recorded, not opportunistically fixed"*. Three of the findings
below (A5/F5, A6/F3, F6) are about code written hours earlier by the reviewing
process itself. That code has tests and looks sound, but it has not had an
independent read by anything, and it is sitting uncommitted alongside a
modified `CLAUDE.md`. **Phase 0 exists because of this.**

---

## Independent verification results

| Claim | Verdict |
|---|---|
| A1/F1 — airline identity forks in production | **Confirmed.** `LATAM` (33,525 google + 234 fast_flights) vs `LATAM Airlines` (135 kayak); `ITA` (11,741 + 127) vs `ITA Airways` (19 kayak). Same-snapshot forked pairs found at snapshots 7242, 7238, 7124, 7122, 7118, 7117, 7116 |
| A3/N3 — API endpoints omit `delay=False` | **Confirmed, both sites** (`api.py:42`, `api.py:106`); all three `pages.py` sites pass it |
| A2/N1 — worker performs three `_RENDER_TIMEOUT_S` waits | **Confirmed.** `kayak_render.py:96` warmup goto, `:97` dwell, `:99` main goto, `:38` stable-wait cap. `_warmup_sequence` yields exactly one URL, so worst case is 45+5+45+45 = **140s** against a 112.5s kill cap |
| A4/N2 — ImportError paths silent | **Confirmed**, both `google_flights.py:29` and `fast_flights.py:25` return `[]` with no `last_error` |
| A7/F7 — bracket read of a migration column | **Confirmed**, `pages.py:907`; `scheduler.py:111` correctly uses `.get()` |
| A8/N4 — ungrounded calendar date | **Confirmed as a gap, zero manifestation.** 0 rows outside `[depart_date, depart_date+1]` across the whole table; the only next-day rows are 6 occurrences, all at hour `00` |
| Suite state | **473 passed, 3 deselected**, matching both reports |

---

## Consolidated findings, and the fix/no-fix call

| ID (022/023) | Finding | Call |
|---|---|---|
| F1 / A1 | Airline identity forks for name-variant carriers | **Fix** — Phase 4 |
| N3 / A3 | `POST /api/trackers/{id}/search` + `POST /api/trackers` can hang 15 min | **Fix** — Phase 1 |
| F7 / A7 | `tracker["kayak_enabled"]` bracket read | **Fix** — Phase 1 |
| N2 / A4 | Broken fli/fast_flights import is invisible | **Fix** — Phase 1 |
| F8 / A10 | `60` hardcoded where `DEFAULT_INTERVAL_MINUTES` is authoritative | **Fix** — Phase 1 |
| F5 / A5 | `_rebase_departure_date` rewrites identity silently | **Fix** — Phase 2 |
| N1 / A2 | Worker budget derived from a false premise, test pins it wrong | **Fix** — Phase 3 |
| F3 / A6 | Airline checkbox identity flips with blend composition | **Fix** — Phase 5 |
| F10 / A12 | One source can be listed twice in a merged row | **Fix** — Phase 5 (trivial, same file) |
| F4 / A11 | `_relative_minutes` duplicates `base.html` bucketing | **Test only** — Phase 5 |
| F2 | `_AIRLINE_NAME_TO_CODE` has an undocumented second job | **Doc only** — Phase 6 |
| N4 / A8 | Calendar date is ungrounded | **No fix** — watch |
| F6 | Rollover cutoff conflates product and data-integrity questions | **No fix** — watch |
| N5 / A9 | `_airline_grounded` substring match is loose | **No fix** — record |
| F9 / A13 | `_validate(depart_date=None)` optional by convention | **No fix** |
| N6 | Two timestamp parsers with identical format lists | **No fix** — record |
| N7 | A stale source vanishes from the detail page | **No fix** — product decision, → TODO |
| 023 arch. | Codeshares are a second identity fork | **No fix** — → TODO roadmap |

### Why the "no fix" calls

- **N4/A8 and F6 (date grounding).** Zero manifestations in the entire table.
  Writing a date-window guard now means adding a fourth narrow guard against a
  defect that has never occurred, on the same page where a false positive
  silently discards real prices. The correct response to a gap with no
  occurrences is a standing data check, which is what Phase 6 adds. Revisit the
  moment the query returns a row.
- **N5/A9 (`_airline_grounded` substring).** The proposed fix *tightens* a
  guard, and CLAUDE.md is explicit that the IATA-vs-full-name case must be
  fixed prompt-side and the grounding check must not be weakened *or carved
  up*. Tightening it to a line-based match risks dropping legitimate rows to
  prevent a failure observed zero times. Note it; do not touch it.
- **F9/A13, N6.** Real observations, no failure mode either can produce today.
  Fixing them is churn on the eve of a large feature.
- **N7.** A source silently vanishing from the detail page is a UI gap, not a
  broken invariant — `/monitor` still carries the WARNING. It belongs on the
  TODO with the other UI work, not in a correctness remediation.

---

## Implementation plan

Ordering principle: **certain and cheap before expensive and invasive**, with
the one item that needs a data migration isolated so it can be aborted without
stranding anything else. A1 goes after the one-liners even though it is ranked
first by both reports — it is the only phase that touches stored data, and the
one-liners remove live failure modes (a 15-minute HTTP hang, an invisible
dependency break) in minutes.

### Phase 0 — land the working tree (prerequisite, no code)

Nothing below starts until the eight uncommitted files are committed. They
contain a feature (`_rebase_departure_date`) written during a review that was
scoped not to write code, plus `CLAUDE.md` edits.

1. Review `git diff` in full — this is the independent read that code never got.
2. Commit as its own change, separate from any remediation.

**Verify:** `git status` clean; `473 passed, 3 deselected`.

### Phase 1 — the certain one-liners

All four are single-token changes with no design content.

1. `api.py:42` and `api.py:106` → `search_and_store(..., delay=False)`.
2. `pages.py:907` → `not tracker.get("kayak_enabled")`.
3. `google_flights.py:29` / `fast_flights.py:25` → set
   `self.last_error = f"import failed: {type(e).__name__}: {e}"` and
   `self.last_error_level = "ERROR"` before `return []`.
4. `pages.py:551` → import `DEFAULT_INTERVAL_MINUTES` for the *first* `60`
   only. **The second `60` is an independent staleness floor and must stay** —
   give it its own named constant so the two are never conflated again.

**Tests (new):**
- `kayak_enabled=1` + `kayak_next_due_at` in the past → `POST
  /api/trackers/{id}/search` returns and `asyncio.sleep` is never called with
  a jitter delay (monkeypatch to record).
- toggle-kayak against a tracker row lacking `kayak_enabled` returns a
  response, not `KeyError`.
- `sys.modules["flights"] = None` → `search()` returns `[]` **and**
  `last_error` is set. Same for the fast_flights sentinel.

**Verify:** full suite; paste into `.agent/reports/024-phase-1.md`.

### Phase 2 — observability on the rebase

`_validate` returns `(validated, rebased_count)`; `_search_inner` puts
`rebased_rows` in the sample sidecar `record` and, when non-zero and no other
message has been set, sets `last_error_level = "WARNING"` naming the count.

The sidecar counter is the minimum and costs nothing; the WARNING is what makes
it visible on `/monitor`, which is the only channel that has ever caught this
class of problem in this project.

**Test:** a search where exactly one row rolls over asserts the counter and the
WARNING.

**Verify:** full suite; `.agent/reports/024-phase-2.md`.

### Phase 3 — make the worker budget count its real waits

Do not just bump the factor. Replace the magic factor with an explicit sum, so
the premise cannot rot silently again:

```python
_WARMUP_TIMEOUT_S = 20.0          # its own cap; the homepage is not the results page
_MAX_WARMUP_DWELL_S = 5.0         # upper bound of KayakRenderConfig.warmup_dwell_s
_WORKER_STARTUP_ALLOWANCE_S = 15.0
_WORKER_TIMEOUT_S = (
    _WARMUP_TIMEOUT_S + _MAX_WARMUP_DWELL_S
    + 2 * _RENDER_TIMEOUT_S            # main goto + _wait_for_results_stable
    + _WORKER_STARTUP_ALLOWANCE_S
)
```

That is 130s (vs today's 112.5s cap against a 140s worst case), and
`_OVERALL_TIMEOUT_S` recomputes to 220s. The warmup goto must then actually use
`_WARMUP_TIMEOUT_S` in `kayak_render.py:96`. Re-verify the
`_OVERALL_TIMEOUT_S` slack assertion still clears 25s.

**Test:** rewrite `test_the_worker_cap_covers_both_render_waits` — its name and
its arithmetic are both wrong — to enumerate every `timeout=`/`cap_seconds=`
wait in `kayak_render.py` and assert the parent cap clears their sum plus the
dwell. Adding a fourth wait must fail the suite.

**Verify:** full suite + one live Kayak cycle showing a normal ~55s render is
unaffected; `.agent/reports/024-phase-3.md`.

### Phase 4 — airline identity (the only data migration)

**Gate: needs explicit approval before the backfill runs — it rewrites
`flight_key` on ~246k rows.**

1. Move `_AIRLINE_NAME_TO_CODE` out of `pages.py` into a new leaf module
   `backend/airlines.py` that both `fingerprint.py` and `pages.py` can import.
   `pages.py` cannot be imported by `fingerprint.py` — that import direction is
   part of why the two normalisations diverged.
2. `_normalize_airline` consults the map: mapped names collapse to their IATA
   code, unmapped names keep today's behaviour.
   ```python
   normalized = " ".join((airline or "").split())
   return (_AIRLINE_NAME_TO_CODE.get(normalized.upper()) or normalized).casefold()
   ```
   Keys become `la|dep|arr` for mapped carriers. Keys are opaque identifiers and
   the `airline` column is untouched, so readability is unaffected. The
   alternative — mapping variants to a canonical *name* — needs a second map to
   maintain and buys only prettier keys.
3. Back up the DB, then re-run `scripts/backfill_019_flight_keys.py <db>`. It
   calls `make_flight_key` itself, so stored keys agree with the running code by
   construction — **do not hand-write the SQL equivalent**, and note that the
   `LOWER()`/`TRIM()` SQL shortcut is now doubly wrong since it cannot consult
   the map.

**Safety notes established by both reviews and re-checked here:**
- `historical_best_price` is `MIN` over rows regardless of key — unaffected.
- Post-merge, two rows in one snapshot legitimately share a key (google `LATAM`
  + kayak `LATAM Airlines`). All eight `flight_key` consumers were audited
  clean for exactly this by both reports; that is what makes the merge safe.
- `_group_duplicate_price_rows` groups on `(flight_key, price, is_missing)`, so
  the €818/€824 pair stays two rows — correct, since the prices disagree.

**Tests:** `make_flight_key(airline="LATAM") == make_flight_key(airline="LATAM
Airlines")`; broad form over every pair sharing a map entry. Both fail today.

**Verify:** full suite; a live cycle on tracker 20 or 21 showing one chart line
where two existed; `.agent/reports/024-phase-4.md`.

### Phase 5 — display stability

1. **A6/F3:** emit the group's stable identity key as the checkbox `value`,
   set `f["airline"]` in `window.allFlights` to the same key, render the pretty
   name as the visible label. Sequenced after Phase 4 deliberately — once stored
   keys merge, the display name is the only remaining instability.
2. **A12/F10:** dedupe the `sources` list in `_group_duplicate_price_rows`
   (`dict.fromkeys`) so one source cannot appear twice.
3. **A11/F4 (test only):** boundary table for `_relative_minutes`
   (`0, 1, 59, 60, 1439, 1440`) with a comment naming
   `base.html::updateRelativeTimes` as its counterpart. The JS side stays
   unpinned — a browser test is not worth it here; the comment is the mitigation.

**Test:** build the detail context twice (Kayak-only blend, then blended) and
assert a carrier's checkbox value is byte-identical.

**Verify:** full suite; `.agent/reports/024-phase-5.md`.

### Phase 6 — documentation and standing checks

CLAUDE.md, all of which both reports flag:
- Test count `456` → the count after this plan lands.
- The `flight_key` note gains the variant-name limitation **and its
  resolution** (Phase 4), including that TAP-style case differences were always
  bridged and only shortened-vs-full names forked.
- The render worker performs **three** `_RENDER_TIMEOUT_S`-capped waits.
- Manual-trigger endpoints must pass `delay=False`; name all five sites.
- `_AIRLINE_NAME_TO_CODE`'s second job as the facet grouping identity, and the
  deliberate `LOGO_UNAVAILABLE_CODES` divergence between its two consumers.
- `_relative_minutes` tracks `base.html::updateRelativeTimes`.

TODO.md:
- Tick the code-review roadmap item, pointing at 022/023/024.
- Add N7 (stale source invisible on the detail page) to the UI list.
- Add codeshare pairs to the "Additional sources + expandable flight detail"
  roadmap item — that is where one itinerary with several sellers belongs.

**Standing data checks** (record in the TODO, run before trusting a Kayak-only
low): rows whose departure date falls outside `[depart_date, depart_date+1]`
(N4/A8), and same-carrier/same-clock-time pairs one day apart with departure
hour ≥ 3 (F6). Both return zero today.

---

## What this plan does not do

- It does not touch `historical_best_price` semantics.
- It does not tighten `_airline_grounded`, and Phase 4 must not be read as
  licence to — merging *names* in the identity layer is the opposite of
  weakening the grounding check that verifies the name was printed.
- It does not add a date guard. The data says there is nothing to guard yet.
- It leaves the two live watch items (airline grounding IATA-vs-name, the
  `| Ad` / `Sponsored` placement variants) open. As the roadmap item said when
  it queued this review: only live traffic closes those.
