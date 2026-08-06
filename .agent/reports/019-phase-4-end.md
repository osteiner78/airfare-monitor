# Plan 019 — Phase 4 (promote) — end report

Date: 2026-08-06. Branch `017-kayak-source`.

---

## 4.0 — `_time_grounded` shipped into `_validate`

Ported the benchmark's am/pm check next to `_price_grounded` in
`backend/sources/kayak.py`. `_validate` now drops any row whose departure OR
arrival clock time is absent from the rendered body, logging at WARNING like
the price checks, so `search()`'s existing dropped-count path surfaces it on
`/monitor`.

Two questions the port had to settle, since the benchmark's version behaves
differently from production's neighbours (both decided with the user before
implementing):

- **Unparseable time → keep the row.** `_canonical_timestamp` deliberately
  stores such a value ("the row is still worth storing and `_validate` is the
  guard that matters"). The benchmark's `_time_grounded` returns `False` there,
  i.e. drop; porting that verbatim would have silently reversed an explicit
  existing decision for a reason the plan never argued.
- **24-hour pages → ground against the 24h form.** The check is otherwise
  12-hour-English-only, and Kayak force-redirects by egress geography (a pt-BR
  page prints `00:30`, not `12:30 am`), so a verbatim port would drop **every**
  row of a perfectly good page — the same silent data loss `_price_grounded`'s
  dot-thousands fallback exists to prevent. The 12-hour probe runs **first and
  wins**: on a page printing `12:30 am`, a bare `12:30` lookup would match that
  very line and wave through the misread this check exists to catch. A page
  printing no recognisable clock time at all grounds nothing, so it is no
  evidence against a row (same abstention as `_looks_blocked_structurally`).

### Equivalence to the benchmark, on real data

Not asserted — measured. Every benchmark record carrying `flight_keys` was
replayed through both the benchmark's `_keys_time_grounded` and the production
port, against the real captured bodies:

```
agree    {'deepseek-v4-flash-free': 50, 'mimo-v2.5-free': 50, 'laguna-s-2.1-free': 40,
          'longcat-2.0-free': 50, 'nemotron-3-ultra-free': 10, 'north-mini-code-free': 4} 204
disagree {} 0
```

What the shipped check would have dropped, per model:

| model | runs | runs with a bad row | rows | rows dropped |
|---|---|---|---|---|
| deepseek-v4-flash-free | 50 | 0 | 249 | 0 |
| **mimo-v2.5-free (shipped)** | 50 | **1** | 250 | **1** |
| laguna-s-2.1-free | 40 | 12 | 199 | 13 |
| longcat-2.0-free | 50 | 11 | 250 | 11 |
| nemotron-3-ultra-free | 10 | 0 | 50 | 0 |
| north-mini-code-free | 4 | 0 | 20 | 0 |

mimo's 1-in-50 is exactly the residual ~2% the plan's 4.0 section predicted, and
it is now caught rather than stored. Confirmed the drop is attributable to the
new check and not the old one:

```
price check alone would keep it: True
time check drops it: True
```

### Verification

```
$ docker exec airfare-monitor pytest tests/test_kayak_source.py -v
...
tests/test_kayak_source.py::test_validate_drops_row_whose_clock_time_is_absent_from_rendered_text PASSED [ 75%]
tests/test_kayak_source.py::test_validate_drops_row_whose_arrival_time_is_absent_from_rendered_text PASSED [ 76%]
tests/test_kayak_source.py::test_validate_keeps_row_whose_timestamp_cannot_be_parsed PASSED [ 78%]
tests/test_kayak_source.py::test_validate_grounds_clock_times_against_a_24_hour_page PASSED [ 80%]
tests/test_kayak_source.py::test_validate_does_not_ground_times_against_a_page_printing_none PASSED [ 81%]
tests/test_kayak_source.py::test_search_drops_row_whose_clock_time_is_hallucinated PASSED [ 83%]
============================= 65 passed in 37.14s ==============================

$ docker exec airfare-monitor pytest tests/ -q -k "not slow"
376 passed, 3 deselected in 26.34s     (was 370 before this phase)
```

Commit: `683352c [phase-4.0] Ground extracted clock times against the rendered page`

---

## Promotion proper

`PATCH /trackers/20/toggle-kayak` → `200`, `kayak_enabled=1`, logged as
`INFO kayak_enabled`. Then one manual cycle, pre-render delay skipped:

```
$ docker exec airfare-monitor python -c "...search_and_store(20, delay=False)"
INFO:httpx:HTTP Request: POST https://opencode.ai/zen/v1/chat/completions "HTTP/1.1 200 OK"
51.9s total
```

Snapshot **6390**, `115 results` — **both sources in the same snapshot**, which
is what plan 017 Phase 3 built:

| source | rows | min | max |
|---|---|---|---|
| google_flights | 110 | 800.0 | 6055.0 |
| kayak | 5 | 654.0 | 806.0 |

No `kayak_search_error`. Sidecar: `outcome: extracted`, `extracted_rows: 5`,
`validated_rows: 5`, `blocked_by_markers/structure: false`, `elapsed_s: 49.64`.
All 5 Kayak rows stored `currency = EUR`.

### 6.3 — `best_source` reflects the genuinely cheapest source

```
best_price 654.0   best_source "kayak"   previous_best_price 800.0
historical_best_price 654.0   (was 708.0)
```

Correct: Kayak really did quote the cheapest fare this cycle (654 vs Google's
800), verified by hand below. **And the cross-source merge fired for the first
time in production** — one physical flight, one key, two sources:

```
iberia|2026-08-21T14:00:00|2026-08-22T11:05:00  ->  kayak:732.0, google_flights:800.0
```

That is plan 017 Phase 1 + plan 019 Phase 2 doing exactly what they were built
for, on live data.

**The trend chip did move**, contrary to 6.3's literal wording. It moved because
a genuinely cheaper real fare entered the comparison, not because Kayak's rows
double-counted an existing one — the merge above shows the de-duplication
working. 6.3's concern was a phantom move; this is a real one. See the price
oscillation caveat under 6.4.

### 6.6 — hand spot-check against kayak.com

An independent fresh render of the same URL (a second page load, not the body
the LLM read):

```
body_len: 20674   currency: EUR
  EUR 654 on page: True     EUR 732 on page: True     EUR 775 on page: True
  EUR 796 on page: True     EUR 806 on page: True
cheapest block: 3:50 am – 10:20 pm+1 / Arajet, Iberia / 3 stops / PUJ 5h 20m layover ...
                / 37h 30m / GRU - ZRH / €654 / Economy Cabin + Basic / Select
```

€654 GRU→ZRH on 2026-08-21, 3:50 am → 10:20 pm+1, 37h 30m, 3 stops, self-transfer
via PUJ/SJU/MAD. The stored row matches the page. **The price that set a new
all-time low is real.** Rows at 732 / 775 / 796 all match genuine result blocks
too.

**But one of the five stored rows is not a result row** — see Finding 1.

### 6.4 — a Kayak failure leaves the main sources undisturbed

Run against a `.backup` copy of the production DB (`data/airfare-64check.db`,
deleted afterwards) so production was untouched; `kayak_next_due_at` reset to
`NULL` per arm so the Kayak path was actually reached.

| arm | log | snapshot | `kayak_next_due_at` |
|---|---|---|---|
| A — `search()` returns `[]` with a source-level WARNING (block) | `WARNING kayak_search_error  KayakSource: Kayak render appears blocked by bot detection (markers)` | created, 110 fli rows | advanced 01:38 → **04:14** |
| B — `search()` raises (`Connection closed while reading from the driver`) | `ERROR kayak_search_error  Connection closed while reading from the driver` | created, 110 fli rows | advanced → **04:45** |

Both degrade to zero extra rows, both log under the distinct `kayak_search_error`
event, both advance the due time so a failed run cannot hot-retry on the next
tick. The main loop's `search_done` fires normally in both.

*(A first attempt at arm A logged nothing: it patched `last_error` on the class,
which `__init__`'s own assignment shadows, so the scheduler read `None`. A mock
artifact, not a production bug — re-run setting the instance fields the way a
real blocked render does, which is the row above.)*

**Caveat, and it is the honest reading of "the displayed price is undisturbed":**
the fli rows are undisturbed, but the *headline price is not*. With Kayak's 654
absent from the new snapshot, `best_price` returns to Google's 800 and
`best_source` to `google_flights`. So a Kayak-exclusive cheap fare makes the
dashboard price oscillate 654 ↔ 800 with Kayak's success rate. This is the
price-level form of the churn the plan already names as out of scope
("Kayak-exclusive flights will churn new/missing whenever a Kayak run fails"),
and it needs the same fix: per-source success recording per snapshot.

---

## Findings (new, discovered by the live run — not in the plan)

### 1. Paid-placement prices get welded onto a real itinerary — a phantom row

The stored row `Arajet | 2026-08-21T03:50 | 2026-08-22T22:20 | €806 | 3 stops`
is not a search result. **Every** occurrence of `€806` in the body sits inside
an Expedia paid placement:

```
Book your flight to unlock more savings ... This is a paid placement from Expedia.
You're seeing it because of its relevance to your search and the advertiser's bid.
€806 View Deal
...
€806 / 1 stop / €1,228 / nonstop / Expedia / | / Ad / €806 / Economy / View Deal
```

The model took the ad's price and attached it to the neighbouring cheapest
itinerary's times and carrier (`Arajet, Iberia` → `_first_carrier` → `Arajet`),
while the *genuine* €654 `Arajet, Iberia` row was dropped in favour of the
duplicate €654 `Multiple airlines` row below it. Both guards pass by
construction: 806 is printed on the page, and 3:50 am / 10:20 pm are printed on
the page. Grounding checks a value exists; it cannot check the value belongs to
the row it was attached to.

Impact today: one wrong row in the results table and one phantom `flight_key`
per cycle. Impact tomorrow: `historical_best_price` is `MIN` over all rows and
is never recomputed, so an ad priced *below* the organic results would lower a
tracker's all-time low permanently and fire a notification on the way in. Here
the ad was 23% above the real cheapest, so nothing was corrupted — that is luck,
not a guarantee.

Cheapest plausible fix (not done, out of Phase 4's scope): strip ad blocks in
`_results_section`, which already trims the body and already keys on structure
— the placement text is distinctive and verbatim (`"This is a paid placement
from"` / `"| Ad"` / `"View Deal"`).

### 2. `"Multiple airlines"` is a placeholder, not a carrier

Two of five rows stored `airline = "Multiple airlines"` — Kayak's own label for
some mixed-carrier itineraries. `_first_carrier` cannot help: there is no
carrier in the string. Such rows can never merge with the Google sources (which
name a real carrier), and two genuinely different itineraries sharing both clock
times would collide on one key. Plan 019 task 2.6 handled the comma-joined form
(`"Azul, easyJet"`); this second form was not in the sample set it was decided
from.

### 3. Three snapshots for tracker 20 within 21 seconds

`6372 / 6383 / 6387` at `01:24:24 / 01:24:29 / 01:24:45`, all 110 results,
before this phase touched anything. Unrelated to Kayak and not investigated.

---

## Deviations from the plan

- **The plan's only Phase 4 test did not exist.** `test_validate_drops_row_whose_clock_time_is_absent_from_rendered_text`
  was named at plan line 419 but never written by the orchestrator, so there was
  nothing red to make pass. Flagged and stopped; the user chose "I write it,
  flagged as a gap". I wrote it plus five more pinning the behaviour the port
  had to decide (arrival-side misread, unparseable-keep, 24h page, no-times
  page, and end-to-end wiring through `search()`). No orchestrator test was
  modified.
- **6.3's "the trend chip did not move purely because Kayak joined" is reported
  as observed, not forced.** It moved, for a real reason. Recorded rather than
  massaged.
- **6.4 was simulated on a DB copy**, not waited for in production. The failure
  it describes cannot be forced on the live tracker, and both arms exercise the
  exact scheduler path. Real failures will still show up on `/monitor` as
  `kayak_search_error`.

## Follow-ups (not done)

1. **Ad-block contamination** (Finding 1) — a phantom row per cycle today, a
   permanent `historical_best_price` corruption vector tomorrow. The one item
   here that touches data the project treats as irreversible.
2. **`"Multiple airlines"` as an identity value** (Finding 2).
3. **Per-source success recording per snapshot** — already named in the plan's
   out-of-scope list; the 654 ↔ 800 oscillation under 6.4 is the same defect
   showing up in the headline price rather than the flight list.
4. **The 21-second snapshot triple** (Finding 3).

## Confidence

**likely-good.** 4.0 is certain — measured equivalent to the benchmark on 204
real records, full suite green. Promotion is confirmed working end to end
(same-snapshot rows, EUR, a real cross-source merge, correct `best_source`,
graceful degradation on both failure arms, the new low verified by hand against
a fresh page load). It is not "certain" because the live run also surfaced
Finding 1: one of the five promoted rows was an advertisement, and Kayak is now
enabled on tracker 20 with that behaviour unguarded.

**Rollback if wanted:** `curl -X PATCH http://localhost:8100/trackers/20/toggle-kayak`
