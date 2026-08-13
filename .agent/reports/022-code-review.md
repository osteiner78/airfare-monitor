# 022 — Code review: cross-file invariants that nothing pins

**Target:** `TODO.md` lines 36–99 — audit for the repeating defect shape, not style.
**Date:** 2026-08-13
**Verdict:** **significant issues** — no data-corruption bug found, but the
cross-source merge fails live for name-variant carriers (F1, now confirmed in
production data, not just by code reading), one documented contract is
violated on the API search endpoint (N3), and the timeout-budget invariant is
pinned against the wrong arithmetic (N1).

**Surface reviewed:** `backend/fingerprint.py`, `backend/sources/kayak.py`,
`backend/sources/kayak_render.py`, `backend/sources/fallback.py`,
`backend/sources/fast_flights.py`, `backend/sources/google_flights.py`,
`backend/sources/base.py`, `backend/scheduler.py`, `backend/main.py`,
`backend/db.py`, `backend/pages.py` (`_build_detail_context`,
`_group_duplicate_price_rows`, airline/filter helpers), `backend/api.py`,
`frontend/static/filters.js`, `frontend/templates/base.html`,
`partials/detail_page.html`, `partials/results_table.html`, the uncommitted
working tree, and the production DB (`data/airfare.db`).

**Test integrity: clean.** `git diff tests/` is +139/−0 — pure additions to
`tests/test_kayak_source.py`, no existing test modified, weakened, deleted,
commented out or marked skip/xfail. Suite re-run against the reviewed state:
`473 passed, 3 deselected`.

**Note on process:** an earlier pass of this review (its output was the
untracked `022-code-review.md` this file consolidates) made code changes
mid-review — the `_rebase_departure_date` bound, the airline grouping and
`_relative_minutes` are all uncommitted working-tree changes written during
that pass. The TODO's own instruction ("findings get recorded, not
opportunistically fixed mid-review") was not held to. Findings below are
against the final state of the working tree; F5/F6 concern code written hours
ago rather than settled code.

---

## Findings, ranked by blast radius

### F1 🔴 Airline identity is normalised in two layers that disagree — confirmed live in production data

**Invariant broken:** one physical flight has one `flight_key` across sources.

Two normalisations of the same field exist:

`backend/fingerprint.py:4-11` — decides the **stored, permanent** identity:
```python
def _normalize_airline(airline: str) -> str:
    return " ".join((airline or "").split()).casefold()
```

`backend/pages.py:770-772` (new) — decides the **filter facet**:
```python
def _airline_identity(name: str) -> str:
    normalized = " ".join((name or "").split())
    return _AIRLINE_NAME_TO_CODE.get(normalized.upper()) or normalized.casefold()
```

Casefolding bridges `"GOL"`/`"Gol"`. It cannot bridge `"LATAM"` vs
`"LATAM Airlines"` or `"ITA"` vs `"ITA Airways"` — and the map carries both
spellings of each (`pages.py:188-189`, `207-208`), which is itself evidence
both spellings are seen live from different sources.

This is no longer a hypothesis — the production DB proves it:

```
LATAM | LATAM Airlines | 2026-08-21T18:20:00 | 2026-08-22T10:35:00 | 827.0 | 824.0 | google_flights | kayak
Tap Air Portugal | TAP AIR PORTUGAL | 2026-08-21T20:45:00 | 2026-08-22T17:15:00 | 817.0 | 684.0 | fast_flights | kayak
```

Same physical flight, same clock times, two `flight_key`s, two table rows, two
chart lines, two colour slots, two sticky keys. The sidebar merges what the
data does not: one checkbox claims a merged carrier while the cross-source
merge — the thing plans 017/019 exist to deliver — silently fails below it.
`_group_duplicate_price_rows` groups by `flight_key`, so even identical prices
will not collapse the pair.

This is the `fast_flights::_to_iso` shape from the TODO exactly: a local
assumption (casefold is enough) invalidated by a distant change (Kayak
emitting full names where Google emits short ones), no re-audit of callers.

**Fix** — belongs in the identity layer, not the view:
```diff
--- a/backend/fingerprint.py
+++ b/backend/fingerprint.py
-    return " ".join((airline or "").split()).casefold()
+    normalized = " ".join((airline or "").split())
+    return _AIRLINE_NAME_TO_CODE.get(normalized.upper(), normalized).casefold()
```
Requires moving `_AIRLINE_NAME_TO_CODE` to a module both can import (it lives
in `pages.py`, which fingerprint cannot import — the current split is partly
why this happened), plus a backfill via `scripts/backfill_019_flight_keys.py`
(it calls `make_flight_key` itself, so stored keys stay correct by
construction). Recorded, not applied.

**Pinnable:** yes — `assert make_flight_key(airline="LATAM") ==
make_flight_key(airline="LATAM Airlines")` fails today; the broad form asserts
it for every pair of names sharing an `_AIRLINE_NAME_TO_CODE` code.

**Confidence:** certain — observed rows exist in `flight_prices` right now.

---

### F5 🟡 `_rebase_departure_date` rewrites stored identity and reports nothing

**Invariant broken:** `last_error`/`last_error_level` is the only channel
`/monitor` sees, so anything that changes what gets stored must use it.

`kayak.py:871-915` rewrites `departure_time` and `arrival_time` — two thirds of
`flight_key` — and emits no signal at all: not `last_error`, not a `record`
field, not even a `logger.warning` (which per CLAUDE.md would not reach
`system_logs` anyway). Every other correctness action in this file reports:
`_validate`'s four drop paths log, and `_search_inner` surfaces drop counts at
WARNING precisely because a silent shrink "would otherwise look identical to a
clean success".

This is the `FallbackSource` bug's exact shape. It matters here because the
rebase depends on model behaviour already observed to be non-deterministic:
the same printed 00:45 departure was dated on either side of midnight across
otherwise-identical runs. If that behaviour shifts (a prompt edit, a model
swap), rows get relabelled onto `depart_date` and nothing on `/monitor` shows
it.

**Fix** — mirror the `dropped` treatment:
```diff
-            validated = self._validate(rows, body_text, depart_date)
+            validated, rebased = self._validate(rows, body_text, depart_date)
             record["validated_rows"] = len(validated)
+            record["rebased_rows"] = rebased
```
and, when `rebased` is non-zero and nothing else has already set a message,
set `last_error_level = "WARNING"` naming the count. At minimum, put the
count in the sample sidecar `record`, which costs nothing.

**Pinnable:** yes — a search where one row rebases asserts
`last_error_level == "WARNING"` and the message names the count.

**Confidence:** certain.

---

### N3 🟡 `POST /api/trackers/{id}/search` can hang for up to 15 minutes

**Invariant broken:** "pass `delay=False` for manual/test triggers" (the
contract `scheduler.py::search_and_store(delay: bool = True)` documents) —
and a request-return-time expectation for an HTTP endpoint.

`backend/api.py:106`:
```python
await backend.scheduler.search_and_store(tracker_id)
```

The pages UI's equivalent passes `delay=False` (`pages.py:859`). The API
route passes the default — so for a Kayak-enabled tracker whose
`kayak_next_due_at` has passed (about half of all mid-cycle manual triggers,
given the jittered 0.7× cadence), the request sits in the 0–15 min pre-render
`asyncio.sleep` (`scheduler.py:117-118`) before returning. Tracker 20 has
Kayak enabled today, so this endpoint can hang right now. The existing test
(`tests/test_api.py:93`) passes only because test trackers have
`kayak_enabled=0` and never reach the sleep.

**Fix:**
```diff
-    await backend.scheduler.search_and_store(tracker_id)
+    await backend.scheduler.search_and_store(tracker_id, delay=False)
```

**Pinnable:** yes — a test with `kayak_enabled=1` and `kayak_next_due_at` in
the past asserts the endpoint returns without sleeping (or the sleep is
monkeypatched to record its call and the test asserts it never happens).

**Confidence:** certain.

---

### N1 🟡 The render-worker budget undercounts a third render wait — and the test pins the wrong arithmetic

**Invariant broken:** `_OVERALL_TIMEOUT_S` must exceed the worst case its
sub-timeouts can actually produce.

`kayak.py:47-52` states the derivation's premise:
```python
# The worker performs both render waits in sequence (page.goto's own cap plus
# _wait_for_results_stable's separate one), so the parent's cap has to clear
# 2 * _RENDER_TIMEOUT_S with room for interpreter and browser startup.
_WORKER_TIMEOUT_FACTOR = 2.5
```

The worker performs **three** waits capped at `_RENDER_TIMEOUT_S` each
(`kayak_render.py:96-100`): the **warmup** `page.goto(warmup_url,
timeout=_RENDER_TIMEOUT_S * 1000)`, the main `page.goto`, and
`_wait_for_results_stable` — plus the 2–5 s warmup dwell. True worst case
≈ 3 × 45 + 5 = 140 s against the parent's 112.5 s kill cap. A slow-but-valid
warmup followed by a slow-but-valid main navigation gets killed ~27 s before
it would have produced a page — the same "lost a good page" shape as the
02:37 2026-08-11 incident, and the same mechanism: a constant derived from
another constant that moved (the warmup sequence was added in plan 018 and
nobody re-audited the cap).

`tests/test_kayak_timeout_budget.py:64-72` pins the *wrong* relationship —
it asserts the worker budget clears `2 * _RENDER_TIMEOUT_S`, so raising the
warmup's weight or adding a fourth sequential wait would pass the suite while
narrowing the real margin. The comment in the test and in `kayak.py` both say
"both", but the code says three.

**Fix:** either fold the warmup into the derivation —
`assert worker_budget > 3 * _RENDER_TIMEOUT_S + warmup_dwell_max` — or shrink
the warmup goto's own timeout below `_RENDER_TIMEOUT_S` so the parent's cap
derivation stays honest. The fix is the test + comment; the constants can
stay if the arithmetic is re-verified.

**Pinnable:** yes — a parametrised count of every `timeout=` /
`cap_seconds=` wait inside the worker against the parent's budget, so adding
a wait fails the suite.

**Confidence:** certain on the arithmetic; speculative on real-world impact
frequency (needs both gotos in the slow tail, though they are correlated —
same host, same network conditions).

---

### N2 🟡 A broken fli/fast_flights import degrades to total silence

**Invariant broken:** the observability contract — a source returning nothing
must say why.

`google_flights.py:24-30` and `fast_flights.py:23-26`:
```python
try:
    ...
    from fli.search import SearchFlights  # noqa: F401
except ImportError:
    return []
```
Both ImportError paths return `[]` **without setting `last_error`**. Then
`fallback.py:51-54` composes an error only `if primary_error or
secondary_error:` — with neither set, `FallbackSource.last_error` stays None,
the scheduler logs nothing, and the cycle records `search_done … 0 results`.
A missing or broken dependency (fli uninstalled in a rebuild, an import
failing inside `fli.search` after a Google page change) looks byte-identical
to "route genuinely has no flights" on `/monitor`. Every other failure mode in
this pipeline reports; the import path — the one most likely to fail exactly
when the upstream library breaks — is the silent one. The TODO's audit
question asked exactly this; the earlier pass marked the area clean and it is
not.

**Fix:** set `self.last_error = f"{type(e).__name__}: {e}"` and
`last_error_level = "ERROR"` in both except blocks.

**Pinnable:** yes — monkeypatch `sys.modules["flights"] = None` (the existing
test sentinel), assert `source.search(...)` returns `[]` **and**
`source.last_error` is set.

**Confidence:** certain that the path exists; speculative frequency (both
libraries are installed today).

---

### N4 🟡 Watch item: no guard checks the calendar date — the fourth narrow guard, already half-built

**Invariant broken:** none yet — the TODO's "assume there is a fourth"
category.

`_time_grounded` (`kayak.py:798-844`) grounds **HH:MM only**; it deliberately
ignores the date. `_rebase_departure_date` then corrects exactly one case —
`depart_date + 1`, hour < 3. Every other wrong date the model can produce
(2+ days off, a +1 day at or past the cutoff, a wrong month) passes all four
grounding checks and is stored as a fabricated identity: `flight_key` carries
the bogus date, the chart gets a phantom point, and the row survives forever
(the price is grounded, so `historical_best_price` is not corrupted — that is
the one saving grace). The advert bug, the nearby-airport promo, and
self-transfer were each "a real value printed on the page, belonging to
something else"; a wrong *date* is the same shape with the date as the
ungrounded field. The prompt now states the date explicitly and the rebase
bounds one window — but nothing rejects the rest of the range.

**Fix:** not a code change yet — a data check first (see the pinnable query
below). If it ever fires, the fix is either date-window grounding in
`_validate` (drop or warn on a departure outside `[depart_date, depart_date +
1]`) or prompt-side.

**Pinnable:** the empirical query — pairs in `flight_prices` sharing airline
and both clock times whose dates differ by exactly one day with departure hour
≥ 3; plus any row whose `departure_time` date differs from the tracker's
`depart_date` by more than one day. Run it against the live DB before writing
any code.

**Confidence:** speculative as to whether it is occurring; certain as to the
gap.

---

### F6 🟡 The rollover cutoff answers a product question while doing a data-integrity job

`_NIGHT_ROLLOVER_CUTOFF_HOUR = 3` is justified, correctly and explicitly, as
a product decision (an 00:45 departure is the night before). But the defect
that made it necessary is *model non-determinism* — the same printed
itinerary extracted on either side of midnight across runs, forking one
flight into two `flight_key`s. Those are two different questions, and they
coincide below 3am by luck. A 03:15 departure exhibiting the same run-to-run
split is **not** rebased and still forks — the plan-019 identity defect,
alive just outside the cutoff, now harder to notice because the symptom
below 3am has been removed. The bound itself is right: the earlier unbounded
version would have silently relabelled off-route fares onto `depart_date`,
poisoning `historical_best_price` permanently. Not pinnable by a unit test —
it is an empirical data check (same query as N4's first half).

**Confidence:** speculative as to occurrence; certain as to the gap.

---

### F3 🟡 The airline group's display name is unstable across cycles, and localStorage keys on it

**Invariant broken:** a persisted filter selection survives a page reload.

`pages.py:774-790` seeds `group["name"]` from whichever variant appears first
in price-ordered `all_flights`, then upgrades ALL-CAPS → mixed-case *within
one request only*. Which variants are present depends on which sources' rows
are in the blend this cycle: when Google's inventory lacks the flight, only
Kayak's `"TAP AIR PORTUGAL"` row exists and the checkbox `value` is the
all-caps form; once Google lists it, `"Tap Air Portugal"` wins
(`detail_page.html:81` renders `value="{{ a.name }}"`).

`filters.js:23-30` persists the **unchecked** set keyed on that value and
`filters.js:209-213` restores with `cb.checked = !uncheckedSet.has(cb.value)`.
When the name flips, a deliberately-unchecked airline silently re-checks.
The checked→unchecked inversion in this changeset fixes the *new airline*
case it was written for; it makes this case quieter (failure mode moved from
"airline vanishes" to "filter turns itself off").

**Fix:** make the stable identity the value and the pretty name the label —
emit the group's `_airline_identity` key as the checkbox `value`, set
`f["airline"]` in `window.allFlights` to the same key, render `a.name` as
the visible label.

**Pinnable:** yes — build the context twice from two source mixes
(Kayak-only, then both) and assert one carrier's checkbox identity is
unchanged.

**Confidence:** likely — mechanism certain; frequency depends on live
inventory overlap.

---

### F7 🟡 `tracker["kayak_enabled"]` — the last bracket read of a migration-added column

`backend/pages.py:907`:
```python
new_kayak_enabled = not tracker["kayak_enabled"]
```
CLAUDE.md's rule is unqualified: read these columns with `tracker.get(...)`.
Every read on the main search path complies (`scheduler.py:111`); this one
does not. Blast radius is one 500 per request rather than the 2026-08-04
outage, but the TODO flags this category as the one that "will matter
immediately, since Passengers adds columns", and `adults`/`child_ages` will
be read on the detail page as well as the search path.

**Fix:** `not tracker.get("kayak_enabled")`. One word.

**Pinnable:** yes — call the endpoint with a tracker row lacking the column.

**Confidence:** certain.

---

### F2 🟡 `_AIRLINE_NAME_TO_CODE` now has two jobs and only one is documented

`pages.py:176-182` documents the map as the logo lookup for rows with no
flight number. It is now also the airline-grouping identity. Adding a logo
entry silently changes facet counts, best-price-per-airline and which flights
share a checkbox. The two consumers also disagree deliberately:
`_airline_code_from_name` gates on `LOGO_UNAVAILABLE_CODES`, `_airline_identity`
bypasses it (correctly — a carrier with no logo should still merge). That
distinction is held by a comment six lines from the code and nowhere near the
map. Move the note onto the map, and pin the divergence with a test: a code in
`LOGO_UNAVAILABLE_CODES` must still merge its name variants.

**Confidence:** certain.

---

### F4 🟡 `_relative_minutes` duplicates `base.html`'s bucketing in a second language, pinned only by a comment

`pages.py:269-289` states the requirement outright, and the two
implementations (`pages.py` Python, `base.html:23-30` JS) agree boundary by
boundary today. Nothing fails if either drifts — this is the
`_OVERALL_TIMEOUT_S` shape verbatim, held by prose, and the cross-language
split makes "derive one from the other" unavailable, so a test is the whole
mitigation. Two minor precision notes: the server-side badge measures age
*against the newest observation* (`_age_minutes`) while the adjacent
"Fetched" column measures age *against now* — the bucketing matches but the
references differ, which is fine only because the badge's tooltip says so;
and a fractional `age_minutes` (e.g. 0.5) truncates to "just now" while
`is_stale` renders the badge anyway.

**Pinnable:** partially — a boundary table (`0, 1, 59, 60, 61, 1439, 1440`)
pins the Python side; the JS side stays unpinned without a browser test.

**Confidence:** certain that it is unpinned; they agree today.

---

### F8 🟢 `pages.py` hardcodes `60` where `DEFAULT_INTERVAL_MINUTES` is the stated single source of truth

`backend/pages.py:551`:
```python
max_age_minutes = max(2 * (tracker["interval_minutes"] or 60), 60)
```
`main.py::_tracker_is_overdue` imports the constant for the same fallback;
this line duplicates it as a literal, and the constant has already moved once
(180 → 60). The **second** `60` (the staleness floor) is a genuinely
independent value and should stay — or become its own named constant so the
two are never conflated on the next read.

**Confidence:** certain.

---

### F9 🟢 `_validate(depart_date=None)` makes the rollover opt-in by convention

The default exists for test convenience; production has exactly one call site,
and `test_search_rebases_departure_date_end_to_end` pins the wiring. A
required parameter would make the omission unrepresentable rather than merely
tested. Low priority — noted because the audit's brief is exactly "held by
convention, not construction".

---

### F10 🟢 `_group_duplicate_price_rows` can list the same source twice

`group_key` is `(flight_key, price, is_missing)` and `sources` appends
unconditionally, so two rows from one source sharing a key and price render
as "Google Flights, Google Flights". Kayak's `_dedupe_rows` prevents it on
that side; nothing prevents it for Google. Cosmetic.

---

### N5 🟢 `_airline_grounded`'s substring match is vacuous for short carrier tokens

`kayak.py:855-868` grounds with `normalized in body_text.casefold()` — a
substring search. For short names it grounds nearly everything: `"AN"` matches
"and"/"another", `"AZ"` matches "Azul", `"GO"` matches "Google". The currency
check was deliberately built line-based to avoid exactly this trap
(`_page_currency`'s comment about the picker listing every currency). The
concrete risk: a model that returns an IATA code where the page prints a full
name (observed once, `"AT"` for Royal Air Maroc, plan 017 Phase 6) can pass
grounding via an unrelated word containing the code, then store a wrong
airline — a wrong third of `flight_key`. Low likelihood; noted because the
TODO asked for guards answering a narrower question, and this one answers
"do the characters appear somewhere" rather than "is this the row's carrier".

---

### N6 🟢 Two timestamp parsers with identical format lists

`pages.py::_parse_ts` and `main.py::_snapshot_age_minutes` both hardcode
`("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")`. If the stored format ever
changes (it is written by SQLite's `datetime('now')` in three schema
defaults), two call sites must be updated in lockstep. Same drift class as
F4, lower stakes.

---

### N7 🟢 A source dropped for staleness leaves no trace on the detail page

`pages.py:571` skips a group whose latest observation exceeds
`max_age_minutes`, and `source_freshness` (built from `latest_by_group`) then
omits it too — so a Kayak that has been blocked for two cycles simply
disappears from the page, with no "Kayak: stale" indicator. The `/monitor`
WARNINGs do exist, so it is not fully silent; but the detail page — the
place a user reads prices — presents a Google-only world with no hint a
second source exists. Deliberate design; recorded.

---

## What came back clean

- **The `flight_key` dedup-site audit passes, including the eighth consumer.**
  `prev_rows_by_group` / `prev_flights` / `current_flight_map` use
  `setdefault`; `ordered_top_keys` and `all_flights` dedupe to distinct keys
  before consuming a colour slot; `history_by_key` merges on
  `(flight_key, snapshot_id)` with the `snapshot_id ASC` tiebreak intact
  (`db.py:339`); `get_sticky_top_flight_keys` uses
  `GROUP BY snapshot_id, flight_key` with `MIN(price)`;
  `_group_duplicate_price_rows` groups by `(flight_key, price, is_missing)` —
  it does not assume one row per key per snapshot. The TODO's audit question
  comes back clean on all eight.
- **`_dedupe_rows` still reads identity off `_map_result`'s output** (`130b205`
  lesson holds), and the new rebase runs in `_validate` *before* it, so
  rebase-then-dedupe collapses the split pair correctly. That ordering is
  correct but unstated — see test suggestion 6 below.
- **Tracker-column reads on the main search path are all `.get()`** for
  migration-added columns. F7 is off that path (and templates are safe by
  construction — Jinja returns Undefined, not KeyError).
- **The silent-degradation paths inside `KayakSource` are well covered**: all
  six `_search_inner` outcomes set `last_error` *and* `last_error_level`, and
  the `finally` guarantees a sample sidecar even on render failure. F5 and N2
  are the gaps.
- **`_OVERALL_TIMEOUT_S`'s own arithmetic is derived** and guarded — the
  remaining hole is the *premise* it derives from (N1), not the derivation.

---

## Top 3 to fix first

1. **F1 — airline identity divergence.** Confirmed live, permanent in stored
   data, and it defeats the feature two plans were written to deliver.
   Everything else here is recoverable by editing code; this one needs a
   backfill, and the cost grows with every cycle.
2. **F5 — observability on the rebase.** The cheapest fix on the list (one
   counter into `record`) against the failure mode this project has already
   been bitten by twice, and it makes the next data archaeology unnecessary.
3. **N3 — `delay=False` on the API search endpoint.** One word, violates the
   documented contract, intermittent 15-minute request hang, and Passengers
   widens Kayak rollout onto exactly this endpoint's trackers.

N1 is a close fourth — it is the TODO's signature shape (a constant derived
from a constant that moved) and the test currently pins the wrong count of
waits.

---

## Architectural concerns beyond any single file

**Identity normalisation has no home.** It is spread across
`fingerprint.py::_normalize_airline` (stored key), `kayak.py::_first_carrier`
and `_canonical_timestamp` (source-level, inside `_map_result`),
`kayak.py::_rebase_departure_date` (source-level, inside `_validate`) and
`pages.py::_airline_identity` (display). Five functions, three layers, and F1
is what happens when two of them disagree. The audit question for Passengers
is not "is this a dict?" but **"which layer decides identity, and does every
other layer defer to it?"** — right now no layer is authoritative, and the
rebase has added a fourth identity-affecting normalisation whose ordering
relative to the others is held by call order alone.

**Passengers lands on F1, F5 and N3 directly.** `passenger_count` and the
per-person/total decision are a price-semantics change on rows whose identity
is already ambiguous across sources; `child_ages` adds tracker columns read
on both the search path and the detail page (F7's pattern); and the Kayak URL
change makes every captured sample non-comparable — the sidecar note the TODO
demands will collide with F5's missing rebase counter, since both want the
same `record` fields.

---

## Tests that should exist and do not

1. **Airline name variants produce one `flight_key`.** Two `FlightResult`s
   identical but for `airline="LATAM"` vs `airline="LATAM Airlines"` →
   `make_flight_key` returns the same string. *Fails today — that is the
   point (F1).* Broader form: every pair of names sharing an
   `_AIRLINE_NAME_TO_CODE` code must agree.
2. **The API search endpoint does not sleep.** A tracker with
   `kayak_enabled=1` and `kayak_next_due_at` in the past: `POST
   /api/trackers/{id}/search` returns without invoking the pre-render sleep
   (monkeypatch `asyncio.sleep` to record) (N3).
3. **The worker budget covers every wait in the worker.** Parametrise over the
   waits in `kayak_render.py` (warmup goto, main goto, stable-wait cap, dwell)
   and assert the parent cap clears their sum — a new wait fails the suite
   (N1).
4. **A broken dependency is reported.** `sys.modules["flights"] = None` and
   the fast_flights equivalent: `search()` returns `[]` **and** `last_error`
   is set, so `/monitor` shows it (N2).
5. **A rebased row is reported.** A `search()` where exactly one row rolls
   over sets `last_error_level == "WARNING"` and the message or the sidecar
   `record` names the rebase count (F5).
6. **Rebase-then-dedupe collapses to one row.** Two extracted rows for one
   physical flight — one dated `depart_date`, one `depart_date + 1` at 00:45,
   same carrier and price — survive `_validate` and `_dedupe_rows` as a
   *single* row. Pins the three-way ordering (rebase → dedupe → map) that
   currently holds only because `_validate` happens to run first.
7. **Checkbox identity is stable across source mixes.** Build the detail
   context twice — Kayak-only, then blended — and assert one carrier's
   checkbox value is byte-identical (F3).
8. **`_relative_minutes` boundary table.** `0 → "just now"`, `1 → "1m ago"`,
   `59 → "59m ago"`, `60 → "1h ago"`, `1439 → "23h ago"`, `1440 → "1d ago"`,
   with a comment naming `base.html::updateRelativeTimes` as the counterpart
   (F4).
9. **A missing tracker column degrades to "feature off".** The toggle-kayak
   endpoint against a tracker row without `kayak_enabled` returns a response
   rather than raising `KeyError` (F7).

---

## CLAUDE.md updates needed

- **Outdated:** "Current test suite: … 456 passed, 3 deselected". Actual:
  **473 passed, 3 deselected**.
- **Missing, and load-bearing:** the F1 limitation belongs beside the existing
  `flight_key` note — casefolding bridges case differences only, so
  shortened-vs-full carrier names (`"LATAM"`/`"LATAM Airlines"`,
  `"ITA"`/`"ITA Airways"`, `"Tap Air Portugal"`/`"TAP AIR PORTUGAL"`) still
  fork one flight across sources, and are doing so in production right now.
- **Missing:** `_AIRLINE_NAME_TO_CODE`'s second job as the facet grouping
  identity (F2), and the deliberate `LOGO_UNAVAILABLE_CODES` divergence
  between its two consumers.
- **Missing:** the worker actually performs **three** `_RENDER_TIMEOUT_S`-capped
  waits (warmup goto included), not two — update the `_WORKER_TIMEOUT_FACTOR`
  rationale in the Kayak note and `test_kayak_timeout_budget.py` together
  (N1).
- **Missing:** the API `POST /trackers/{id}/search` and `POST /trackers`
  endpoints call `search_and_store` without `delay=False` (N3) — once fixed,
  note it so the next manual-trigger endpoint does not reintroduce it.
- **Missing:** `_relative_minutes` must track `base.html::updateRelativeTimes`
  (F4).
