# 023 — Code review: cross-file invariants audit (TODO.md lines 36–99)

**Target:** codebase-wide audit for the repeating defect shape named in
`TODO.md:36-99` — ordering/derivation couplings, `flight_key` dedup sites,
silent-degradation paths, narrow guards, tracker-column reads. Not a diff
review; the surface is the seams themselves, including the uncommitted
working tree (night-rollover feature, airline facet grouping,
`_relative_minutes`, filters.js persistence inversion).
**Date:** 2026-08-13
**Verdict:** **significant issues** — one identity-layer defect confirmed
live in production data (A1), one documented contract violated on a live API
endpoint (A3), and the render-worker timeout budget derived from a false
premise and pinned that way by its test (A2). No security issue, no active
price corruption found.

**Surface reviewed:** `backend/fingerprint.py`, `backend/sources/kayak.py`,
`backend/sources/kayak_render.py`, `backend/sources/fallback.py`,
`backend/sources/fast_flights.py`, `backend/sources/google_flights.py`,
`backend/sources/base.py`, `backend/sources/__init__.py`,
`backend/scheduler.py`, `backend/api.py`, `backend/main.py`, `backend/db.py`,
`backend/models.py`, `backend/pages.py`, `backend/kayak_samples.py`,
`frontend/static/filters.js`, `frontend/templates/base.html`,
`partials/detail_page.html`, `partials/results_table.html`, the uncommitted
working tree, and the production DB (`data/airfare.db`, 246,257 price rows).

**Test integrity: clean.** `git diff tests/` is +139/−0 — pure additions to
`tests/test_kayak_source.py` (the `_rebase_departure_date` suite: boundaries,
negative cases, end-to-end wiring). No existing test modified, weakened,
deleted, or skipped. Suite independently re-run in the container at the
reviewed state: **473 passed, 3 deselected**.

**Process note:** no code was changed during this review; per the TODO's own
instruction, findings are recorded, not fixed.

---

## Findings, ranked by blast radius

### A1 🔴 Airline identity forks across sources for name-variant carriers — confirmed in production data

**Invariant broken:** one physical flight has one `flight_key` across sources
(the entire purpose of plans 017/019).

`backend/fingerprint.py:4-11` decides the **stored, permanent** identity:
```python
def _normalize_airline(airline: str) -> str:
    return " ".join((airline or "").split()).casefold()
```
Casefolding bridges `"GOL"`/`"Gol"` and `"TAP AIR PORTUGAL"`/`"Tap Air
Portugal"`. It cannot bridge shortened-vs-full names — and the production DB
proves both forms arrive from different sources for the same carrier:

```
airline           source          rows
LATAM             google_flights  33,525
LATAM             fast_flights       234
LATAM Airlines    kayak              135
ITA               google_flights  11,741
ITA Airways       kayak               19
```

Joined against same snapshot + same departure/arrival date-and-clock-time:

```
google     kayak          departure          g-price  k-price  snapshot
LATAM      LATAM Airlines 2826-08-21T18:20   818.0    824.0    7242, 7238
```

Same carrier, same itinerary, €6 apart, two `flight_key`s: two chart lines,
two colour slots, two sticky keys, two table rows, and a per-source delta of
`new` instead of a price movement — the cross-source merge silently fails for
every carrier whose name has two spellings. `_AIRLINE_NAME_TO_CODE`
(`pages.py:183-243`) already carries **both** spellings mapped to one code
(`LATAM`/`LATAM AIRLINES` → LA, `ITA`/`ITA AIRWAYS` → AZ) — that both exist
is itself evidence both are seen live, and the new `_airline_identity`
(`pages.py:770-772`, working tree) uses the map to merge them **in the filter
sidebar only**. The display layer now merges what the stored layer forks: one
checkbox claims a single carrier above two chart lines that nothing will ever
collapse. `_group_duplicate_price_rows` groups by `flight_key`, so even equal
prices would not merge the pair.

This is the TODO's `fast_flights::_to_iso` shape exactly: a local assumption
(casefold is enough) invalidated by a distant fact (Kayak emits full names
where Google emits short ones), no re-audit of the callers.

**Fix** — one normalisation, owned by the identity layer, consulted by the
view layer:
```diff
--- a/backend/fingerprint.py
+++ b/backend/fingerprint.py
-def _normalize_airline(airline: str) -> str:
-    return " ".join((airline or "").split()).casefold()
+def _normalize_airline(airline: str) -> str:
+    normalized = " ".join((airline or "").split())
+    canonical = _AIRLINE_NAME_VARIANTS.get(normalized.upper())
+    return (canonical or normalized).casefold()
```
The variant map must move out of `pages.py` (fingerprint cannot import it —
`pages.py` imports `db`, `scheduler`, `httpx`; the map belongs in a leaf
module both can import, e.g. fingerprint itself with pages importing from
there). Stored keys change, so a backfill is required —
`scripts/backfill_019_flight_keys.py` calls `make_flight_key` itself, so
re-running it keeps stored keys correct by construction. **Not applied —
recorded.** Note `historical_best_price` is unaffected (it is `MIN` over all
rows regardless of key); what is permanently forked is identity, not price.

**Pinnable:** yes — `make_flight_key` for `"LATAM"` vs `"LATAM Airlines"`
must return one key; broad form: every pair of names sharing a variant entry
agrees. *Fails today — that is the point.*

**Confidence:** certain — the forked rows exist in `flight_prices` right now.

---

### A2 🟡 The render-worker budget assumes two `_RENDER_TIMEOUT_S` waits; the worker performs three

**Invariant broken:** a parent cap must exceed the worst case its children's
own caps can produce — the exact invariant the 2026-08-11 data loss taught.

`kayak.py:47-52`:
```python
# The worker performs both render waits in sequence (page.goto's own cap plus
# _wait_for_results_stable's separate one), so the parent's cap has to clear
# 2 * _RENDER_TIMEOUT_S with room for interpreter and browser startup.
_WORKER_TIMEOUT_FACTOR = 2.5
```
The worker performs **three** waits capped at `_RENDER_TIMEOUT_S`
(`kayak_render.py:95-100`):
1. warmup `page.goto(warmup_url, timeout=_RENDER_TIMEOUT_S * 1000)` (line 96)
2. main `page.goto(url, timeout=_RENDER_TIMEOUT_S * 1000)` (line 99)
3. `_wait_for_results_stable(page)` with `cap_seconds=_RENDER_TIMEOUT_S`

plus the 2–5 s warmup dwell (`KayakRenderConfig.warmup_dwell_s`) and the
throwaway UA-probe launch (cold memo — every render is a fresh process).
Legitimate worst case ≈ 3 × 45 + 5 = **140 s** against the parent's kill cap
of 2.5 × 45 = **112.5 s**. A slow-but-valid warmup followed by a slow-but-valid
main navigation is killed ~27 s before it would have produced a page — the
same "lost a good page" outcome as the 02:37 2026-08-11 incident, via the
same mechanism: a constant derived from a premise that moved (the warmup
sequence landed in plan 018; the cap's premise was never re-counted).

`tests/test_kayak_timeout_budget.py:65-72` pins the **wrong** arithmetic:
```python
def test_the_worker_cap_covers_both_render_waits():
    worker_budget = kayak._WORKER_TIMEOUT_FACTOR * kayak._RENDER_TIMEOUT_S
    assert worker_budget > 2 * kayak._RENDER_TIMEOUT_S
```
Adding a fourth sequential wait — or simply reading the worker code — passes
this suite while the real margin narrows. The derivation of
`_OVERALL_TIMEOUT_S` from the worker cap is itself sound and tested; the hole
is the premise underneath it.

**Fix:** either fold the warmup into the factor (`_WORKER_TIMEOUT_FACTOR =
3.5` → 157.5 s, re-verify `_OVERALL_TIMEOUT_S` slack stays ≥ 25 s) or cap the
warmup goto itself below `_RENDER_TIMEOUT_S` and keep 2.5. Either way the
test must count the real waits:
```python
assert worker_budget > 3 * kayak._RENDER_TIMEOUT_S + max_dwell
```

**Pinnable:** yes — parametrise over every `timeout=`/`cap_seconds=` wait in
`kayak_render.py` so a new wait fails the suite.

**Confidence:** certain on the arithmetic; speculative on impact frequency
(both gotos must sit in the slow tail — but they share a host and network
conditions, so the tails are correlated; the 124 s render of 2026-08-11
already exists as proof the tail is real).

---

### A3 🟡 `POST /api/trackers/{id}/search` can hang for up to 15 minutes

**Invariant broken:** the documented contract of
`scheduler.py::search_and_store(delay: bool = True)` — "pass `delay=False`
for manual/test triggers" — and any sane request-latency expectation for an
HTTP endpoint.

`backend/api.py:106`:
```python
await backend.scheduler.search_and_store(tracker_id)
```
The pages router's equivalents all pass `delay=False` (`pages.py:498`,
`pages.py:859`, `pages.py:935`). The API route passes the default — so for a
Kayak-enabled tracker whose `kayak_next_due_at` has passed, the HTTP request
sits in the 0–15 min pre-render jitter sleep (`scheduler.py:117-118`) before
returning. Tracker 20 has Kayak enabled today, so this endpoint can hang
right now. The existing test (`tests/test_api.py:91`) passes only because its
tracker has `kayak_enabled=0` and never reaches the sleep.

`api.py:42` (`POST /api/trackers`) has the same omission — currently inert
because `TrackerCreate` cannot set `kayak_enabled` (`models.py:17-24`), but
it becomes live the day that changes.

**Fix:**
```diff
-    await backend.scheduler.search_and_store(tracker_id)
+    await backend.scheduler.search_and_store(tracker_id, delay=False)
```
(both sites).

**Pinnable:** yes — tracker with `kayak_enabled=1`, `kayak_next_due_at` in
the past; monkeypatch `asyncio.sleep` to record calls; assert the endpoint
returns and no sleep was recorded.

**Confidence:** certain.

---

### A4 🟡 A broken fli/fast_flights import degrades to total silence

**Invariant broken:** the observability contract — `last_error`/
`last_error_level` is the only channel `/monitor` sees, so a source returning
nothing must say why.

`google_flights.py:25-30` and `fast_flights.py:23-26`:
```python
except ImportError:
    return []
```
Both return `[]` **without setting `last_error`**. `fallback.py:51` composes
an error only `if primary_error or secondary_error:` — with neither set,
`FallbackSource.last_error` stays `None`, the scheduler logs nothing
(`scheduler.py:96` gates on `last_error`), and the cycle records
`search_done … 0 results`. A broken dependency (fli dropped in an image
rebuild, an import failing inside `fli.search` after an upstream break) looks
byte-identical to "route genuinely has no flights" on `/monitor`. Every other
failure mode in this pipeline reports; the import path — the one most likely
to fail exactly when the upstream library breaks — is the silent one.

**Fix:** in both except blocks:
```python
except ImportError as e:
    self.last_error = f"import failed: {type(e).__name__}: {e}"
    self.last_error_level = "ERROR"
    return []
```

**Pinnable:** yes — the `sys.modules["flights"] = None` sentinel already
exists for this; assert `search()` returns `[]` **and** `last_error` is set.

**Confidence:** certain the path exists and is silent; speculative frequency
(both libraries are installed today).

---

### A5 🟡 `_rebase_departure_date` rewrites stored identity and reports nothing

**Invariant broken:** anything that changes what gets stored must be visible
through `last_error`/the sample sidecar — the lesson of the `FallbackSource`
fix, whose shape this repeats.

`kayak.py:870-915` rewrites `departure_time` and `arrival_time` — two thirds
of `flight_key` — and emits no signal: no `last_error`, no `record` field,
not even a `logger.warning` (which would not reach `system_logs` anyway).
Every other correctness action in this file reports: `_validate`'s drop paths
log, and `_search_inner` surfaces drop counts at WARNING precisely because a
silent change "would otherwise look identical to a clean success".

The rebase is a deliberate, user-confirmed product decision and its bounds
are right (exactly +1 day, hour < cutoff — the unbounded version would have
relabelled off-route fares onto `depart_date`, poisoning
`historical_best_price` permanently). But it depends on model behaviour
already observed to be non-deterministic (the same printed 00:45 departure
dated on either side of midnight across identical runs). If that behaviour
shifts — a prompt edit, a model swap — rows get relabelled onto
`depart_date` in bulk and nothing on `/monitor` or in the sample sidecars
shows it; discovering that requires diffing stored `flight_key`s by hand.

**Fix** — mirror the `dropped` treatment:
```diff
-            validated = self._validate(rows, body_text, depart_date)
+            validated, rebased = self._validate(rows, body_text, depart_date)
             record["validated_rows"] = len(validated)
+            record["rebased_rows"] = rebased
```
and, when `rebased` is non-zero and nothing else set a message, set
`last_error_level = "WARNING"` naming the count. The sidecar counter alone
costs nothing and is the minimum.

**Pinnable:** yes — a search where one row rebases asserts the counter/
WARNING exists.

**Confidence:** certain the gap exists; speculative that it will ever matter.

---

### A6 🟡 Airline checkbox identity is the display name, which flips with the blend composition

**Invariant broken:** a persisted filter selection survives a page reload.

`detail_page.html:81` renders `value="{{ a.name }}"`; the group's `name` is
seeded from whichever spelling appears first in price-ordered `all_flights`
and upgraded ALL-CAPS → mixed-case within one request (`pages.py:774-790`).
Which spellings are present depends on which sources' rows are in the blend
**this cycle**: when the google group is stale-excluded (`pages.py:571` —
both fli and fast_flights failing), only Kayak's `"TAP AIR PORTUGAL"` rows
remain and the checkbox value is the all-caps form; once Google rows return,
`"Tap Air Portugal"` wins.

`filters.js:23-30` persists the **unchecked** set keyed on that value and
`filters.js:209-213` restores with `cb.checked = !uncheckedSet.has(cb.value)`.
When the name flips, a deliberately-unchecked airline silently re-checks.
The checked→unchecked inversion in this changeset correctly fixes the *new
airline* case it was written for; it moves this case from "airline vanishes"
to "filter turns itself off" — quieter, not gone.

**Fix:** make the stable identity the value and the pretty name the label —
emit the group's `_airline_identity` key as the checkbox `value`, set
`f["airline"]` in `window.allFlights` to the same key, keep `a.name` as the
visible label. (Interacts with A1: once stored keys merge, the display name
becomes the only remaining source of instability.)

**Pinnable:** yes — build the detail context twice (Kayak-only blend, then
blended) and assert one carrier's checkbox value is byte-identical.

**Confidence:** likely — mechanism certain; frequency depends on how often
the google group falls out of the blend (i.e. how often fli fails, which is
exactly what the fallback exists for).

---

### A7 🟡 `tracker["kayak_enabled"]` — a bracket read of a migration-added column

`backend/pages.py:907`:
```python
new_kayak_enabled = not tracker["kayak_enabled"]
```
CLAUDE.md's rule is unqualified: migration-added columns are read with
`tracker.get(...)`, because Active dev guarantees a window where new code
meets an un-migrated table. Every read on the main search path complies
(`scheduler.py:111`); this one does not. Blast radius is one 500 on the
toggle endpoint rather than the 2026-08-04 all-trackers outage — but the TODO
flags this exact category as the one that "will matter immediately, since
Passengers adds columns", and `adults`/`child_ages` will be read on the
detail page as well as the search path.

**Fix:** `not tracker.get("kayak_enabled")`. One word.

**Pinnable:** yes — call the endpoint against a tracker row lacking the
column; expect a response, not `KeyError`.

**Confidence:** certain.

---

### A8 🟢 Watch item: the calendar date is the one ungrounded field

**No invariant broken yet** — the TODO's "assume there is a fourth" category.

`_time_grounded` (`kayak.py:798-844`) grounds **HH:MM only**; `_rebase_
departure_date` bounds exactly one window (+1 day, hour < 3). Every other
wrong date the model can produce — 2+ days off, a +1 day at/after the cutoff,
a wrong month — passes all four grounding checks and stores a fabricated
identity: bogus date in `flight_key`, phantom chart point, row kept forever.
(The price is grounded, so `historical_best_price` is not corrupted — the one
saving grace.) Advert, nearby-airport promo, and self-transfer were each "a
real value printed on the page, belonging to something else"; a wrong *date*
is the same shape with the date as the ungrounded field.

Checked against production: **no manifestation today** — zero rows whose
departure date falls outside `[depart_date, depart_date+1]` across all
246,257 rows; the only next-day rows are tracker 20's six 00:xx occurrences
the rebase exists for. Data check first, code only if it ever fires (fix
would be date-window grounding in `_validate` or prompt-side).

**Confidence:** certain as to the gap; speculative as to occurrence.

---

### A9 🟢 `_airline_grounded` answers "do these characters appear somewhere"

`kayak.py:855-868` grounds with `normalized in body_text.casefold()` — a
substring search. For short carrier tokens it grounds nearly everything:
`"at"` matches the English word "at" (present on every page), `"an"` matches
"and". The currency check was deliberately built line-based to avoid exactly
this trap (`_page_currency`'s comment about the picker listing every
currency). The concrete risk: the model was already observed once returning
an IATA code where the page prints a full name (`"AT"` for Royal Air Maroc,
plan 017 Phase 6); as an *airline*, such a code passes grounding via an
unrelated word and stores a wrong third of `flight_key`. Low likelihood —
noted because the TODO asked for guards answering a narrower question than
the one that matters.

**Confidence:** speculative.

---

### A10 🟢 Two hardcoded `60`s where `DEFAULT_INTERVAL_MINUTES` is the stated single source of truth

`backend/pages.py:551`:
```python
max_age_minutes = max(2 * (tracker["interval_minutes"] or 60), 60)
```
(the first `60` — the fallback — duplicates the constant; the second is a
genuinely independent staleness floor and should stay, ideally as its own
named constant), and `backend/models.py:23`:
```python
interval_minutes: int = 60
```
`main.py::_tracker_is_overdue` imports the constant for the same fallback;
these two sites duplicate it as a literal, and the constant has already moved
once (180 → 60). Same drift class as A2, lower stakes.

**Confidence:** certain.

---

### A11 🟢 `_relative_minutes` duplicates `base.html`'s bucketing in a second language, pinned only by a comment

`pages.py:269-289` (Python) and `base.html:15-34` (`updateRelativeTimes`, JS)
agree boundary by boundary today — verified: `<1 → "just now"`, `<60 → Nm`,
`<24h → Nh`, else `Nd`, truncation semantics included (`int()` vs
`Math.floor`). Nothing fails if either drifts — the `_OVERALL_TIMEOUT_S`
shape held by prose. The cross-language split rules out deriving one from the
other, so a boundary-table test on the Python side is the whole available
mitigation. Minor precision note: the server badge measures age against the
newest observation (`_age_minutes`) while the client "Fetched" column
measures against now — fine, because the badge's tooltip says so.

**Confidence:** certain that it is unpinned; agreeing today.

---

### A12 🟢 `_group_duplicate_price_rows` can list one source twice

`group_key` is `(flight_key, price, is_missing)` and `sources` appends
unconditionally (`pages.py:344-356`), so two rows from one source sharing key
and price render as "Google Flights, Google Flights". Kayak's `_dedupe_rows`
prevents it on that side; nothing prevents it for the Google sources.
Cosmetic.

---

### A13 🟢 `_validate(depart_date=None)` makes the rollover opt-in by convention

The default exists for test convenience; production has exactly one call
site, and `test_search_rebases_departure_date_end_to_end` pins the wiring. A
required parameter would make the omission unrepresentable rather than merely
tested. Low priority — noted only because the audit's brief is exactly "held
by convention, not construction".

---

## What came back clean

- **The `flight_key` dedup-site audit passes, including the eighth
  consumer.** `prev_rows_by_group`/`prev_flights`/`current_flight_map` use
  `setdefault` (pages.py:596, 623, 656); `ordered_top_keys` and `all_flights`
  dedupe to distinct keys before consuming a slot (pages.py:700-711,
  735-743); `history_by_key` merges on `(flight_key, snapshot_id)` with the
  `snapshot_id ASC` tiebreak intact (db.py:339); `get_sticky_top_flight_keys`
  dedupes via `GROUP BY snapshot_id, flight_key` + `MIN(price)` **before**
  `ROW_NUMBER` ranking (db.py:545-555); `_group_duplicate_price_rows` groups
  by `(flight_key, price, is_missing)` and does not assume one row per key.
  The TODO's audit question comes back clean on all eight.
- **`_dedupe_rows` reads identity off `_map_result`'s output** — the
  `130b205` lesson is pinned by
  `test_dedupe_identity_agrees_with_what_actually_gets_stored`
  (`tests/test_kayak_dedupe_and_startup.py:100`). The new rebase runs in
  `_validate` *before* `_dedupe_rows`, so a run that extracts the same
  flight once dated D and once dated D+1 00:45 collapses to one stored row —
  correct, but see test gap 6 below.
- **Tracker-column reads on the main search path are all `.get()`** for
  migration-added columns; templates are safe by construction (Jinja
  Undefined, not KeyError). A7 is the one violation, off that path.
- **`KayakSource`'s degradation paths are otherwise well covered**: all six
  `_search_inner` outcomes set `last_error` *and* `last_error_level`; the
  `finally` guarantees a sample sidecar even on render failure; `search()`'s
  catch-all redacts the API key from the message.
- **`_OVERALL_TIMEOUT_S` is derived and slack-guarded** — the hole is the
  premise under the worker cap (A2), not the derivation above it.
- **No off-route dates in production** (A8's query), no unparseable-timestamp
  pollution visible, and the rebase's bounds are exactly right for the
  observed defect.

---

## Top 3 to fix first

1. **A1 — airline identity fork.** Confirmed live, permanent in stored data,
   defeating the feature two plans were written to deliver, and the fix
   requires a backfill whose cost grows with every cycle. Everything else
   here is a code edit; this one is a data migration.
2. **A5 — observability on the rebase.** The cheapest fix on the list (one
   counter into `record`) against the failure mode this project has been
   bitten by twice (`FallbackSource`, the `_to_iso` rows).
3. **A3 — `delay=False` on the API search endpoints.** One word per site,
   violates a documented contract, intermittent 15-minute HTTP hang live on
   tracker 20 today.

A2 is a close fourth — it is the TODO's signature shape (a constant derived
from a premise that moved) and its test currently pins the wrong count.

---

## Architectural concerns beyond any single file

**Identity normalisation has no home.** It is spread across five functions in
three layers: `fingerprint.py::_normalize_airline` (stored key),
`kayak.py::_first_carrier` and `_canonical_timestamp` (source-level, inside
`_map_result`), `kayak.py::_rebase_departure_date` (source-level, inside
`_validate`), and `pages.py::_airline_identity` (display). A1 is what happens
when two layers disagree, and the rebase just added a fifth
identity-affecting normalisation whose ordering relative to the others is
held by call order alone. The audit question for Passengers is not "is this
a dict?" but **"which layer decides identity, and does every other layer
defer to it?"** — right now no layer is authoritative.

**Codeshares are a second, orthogonal identity fork (observed, not fixed).**
The same DB query surfaced pairs with *different* carriers sharing identical
departure and arrival times — `LATAM`/`Finnair` 18:20, `ITA`/`Lufthansa`
18:55, `Iberia`/`LATAM Airlines` 19:20, `Tap Air Portugal`/`Azul` 20:45 —
the shape of codeshare/marketing pairs. `flight_key` can never merge these by
construction (airline is a third of identity). Recording only: per-person
party pricing (Passengers) will make these near-duplicate rows more visible
and more confusing, and the expandable-row work (TODO "Additional sources")
is the natural place to surface them as one itinerary with multiple sellers.

**Passengers lands on A1, A3, A5 and A7 directly.** New `trackers` columns
read on both the search path and the detail page (A7's pattern), a Kayak URL
change that invalidates every captured sample, and price-semantics changes on
rows whose identity is already ambiguous across sources.

---

## Tests that should exist and do not

1. **Airline name variants produce one `flight_key`.** Two `FlightResult`s
   identical but for `airline="LATAM"` vs `"LATAM Airlines"` →
   `make_flight_key` returns the same string. *Fails today — that is the
   point (A1).* Broad form: every pair of names sharing a variant-map entry
   agrees.
2. **The API search endpoints do not sleep.** Tracker with `kayak_enabled=1`,
   `kayak_next_due_at` in the past: `POST /api/trackers/{id}/search` returns
   without invoking the pre-render sleep (monkeypatch `asyncio.sleep` to
   record) (A3).
3. **The worker budget covers every wait in the worker.** Count the waits in
   `kayak_render.py` (warmup goto, main goto, stable-wait cap, dwell) and
   assert the parent cap clears their sum — adding a fourth wait fails the
   suite; fix `test_the_worker_cap_covers_both_render_waits` to match reality
   (A2).
4. **A broken dependency is reported.** `sys.modules["flights"] = None` and
   the fast_flights equivalent: `search()` returns `[]` **and** `last_error`
   is set (A4).
5. **A rebased row is reported.** A `search()` where exactly one row rolls
   over records the rebase count in the sidecar `record` (or a WARNING) (A5).
6. **Rebase-then-dedupe collapses a split pair.** Two extracted rows for one
   physical flight — one dated `depart_date`, one `depart_date + 1` at 00:45,
   same carrier and price — survive `_validate` + `_dedupe_rows` as a
   *single* row. Pins the three-way ordering (rebase → dedupe → map) that
   currently holds only because `_validate` happens to run first.
7. **Checkbox identity is stable across source mixes.** Build the detail
   context twice — Kayak-only blend, then blended — and assert one carrier's
   checkbox value is byte-identical (A6).
8. **A missing tracker column degrades to "feature off".** toggle-kayak
   against a tracker row without `kayak_enabled` returns a response rather
   than raising `KeyError` (A7).
9. **`_relative_minutes` boundary table.** `0 → "just now"`, `1 → "1m ago"`,
   `59 → "59m ago"`, `60 → "1h ago"`, `1439 → "23h ago"`, `1440 → "1d ago"`,
   naming `base.html::updateRelativeTimes` as the counterpart (A11).

---

## CLAUDE.md updates needed

- **Outdated:** "Current test suite: … 456 passed, 3 deselected". Actual:
  **473 passed, 3 deselected**.
- **Missing, and load-bearing:** A1's limitation belongs beside the existing
  `flight_key` note — casefolding bridges case differences only, so
  shortened-vs-full carrier names (`"LATAM"`/`"LATAM Airlines"`,
  `"ITA"`/`"ITA Airways"`) still fork one flight across sources, and are
  doing so in production right now.
- **Missing:** the render worker performs **three** `_RENDER_TIMEOUT_S`-capped
  waits (warmup goto included), not two — the `_WORKER_TIMEOUT_FACTOR`
  rationale comment and `test_kayak_timeout_budget.py` both state the wrong
  count (A2).
- **Missing:** `POST /api/trackers/{id}/search` and `POST /api/trackers`
  call `search_and_store` without `delay=False` (A3) — once fixed, note it so
  the next manual-trigger endpoint does not reintroduce it.
- **Missing:** `_AIRLINE_NAME_TO_CODE` now has a second job as the facet
  grouping identity (`pages.py::_airline_identity`), with a deliberate
  divergence: `_airline_code_from_name` gates on `LOGO_UNAVAILABLE_CODES`,
  the grouping identity bypasses it (a carrier with no logo must still
  merge).
- **Missing:** `_relative_minutes` (pages.py) must track
  `base.html::updateRelativeTimes` bucket-for-bucket (A11).
