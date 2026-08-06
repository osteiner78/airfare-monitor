# Plan 020 — Keep adverts out of the price data, and finish grounding identity

## Context

Plan 019 Phase 4 promoted Kayak on tracker 20, and it immediately did what it
was built for: **€654 where Google Flights shows €800** on GRU→ZRH, verified
by an independent hand render. One Iberia flight quoted by both sources
collapsed to a single `flight_key` — plan 017 Phase 1 and plan 019 Phase 2
working on real data for the first time.

The same run also stored **an advert's price as a flight**.

### What actually happened, read off the captured body

`data/kayak-samples/20260806T012940.952907.txt`, lines 112-130. A paid
placement sits between the sort-summary tabs and the first genuine result:

```
Best
€654 • 37h 30m                                  <- real cheapest
Quickest
€1,146 • 11h 15m
Other sort
Book your flight to unlock more savings ... This is a paid placement from
Expedia. You're seeing it because of its relevance to your search and the
advertiser's bid. €806 View Deal                <- advert, price inline
Book your flight to unlock more savings
Members can save up to 30% ...
€806                                            <- and again, standalone
1 stop
€1,228
nonstop
Expedia
|
Ad
€806                                            <- and again
Economy
View Deal                                       <- block ends
Go to next result                               <- real result begins
Go to price section
Go to result details
Self-transfer hack
3:50 am – 10:20 pm+1                            <- its times
Arajet, Iberia                                  <- its carriers
3 stops
```

The model welded the advert's **€806** onto the **times and carrier of the
row immediately below it**, producing
`arajet|2026-08-21T03:50:00|2026-08-22T22:20:00 @ €806` — an itinerary that
does not exist at that price. The genuine row for the same itinerary was also
stored, correctly, at €654.

**Both existing guards pass it by construction.** `_price_grounded` asks
whether €806 is printed on the page — it is, three times. `_time_grounded`
asks whether the clock times are printed — they are, on the real row. Neither
asks whether the price *belongs to* the row it was attached to. The guards
are working as designed and simply do not cover this.

**Severity, stated accurately.** Plan 019 and its tests repeatedly said a bad
price corrupts `historical_best_price` "permanently" because it is "never
recomputed". That is wrong, and the wording was mine: `get_historical_best_price`
(`db.py:463`) runs `SELECT MIN(price) …` on **every read**, so deleting the
offending row repairs the displayed figure completely. The correct statement
is that it **never self-corrects** — the damage persists exactly as long as
the row does. This time the advert was dearer than the real fare, so nothing
was distorted at all.

Real worst case: an advert priced *below* the organic fares becomes a
tracker's displayed all-time low and fires a notification, until someone
notices and deletes one row.

---

## Decisions

1. **Strip placements before extraction, don't teach the model about them.**
   A prompt instruction is a request; removing the text is a guarantee. The
   disclosure sentence is verbatim and stable across every captured body
   (`"This is a paid placement from …"`, seen for Expedia, Budget and Avis),
   and `_results_section` already trims the body structurally, so this fits
   the existing seam rather than adding a new one.
2. **Ground the airline too.** `flight_key` is
   `airline|departure_time|arrival_time`. Two of its three components are
   grounded against the rendered page; the third is not. That is a gap in a
   defence built specifically to protect identity — an ungrounded airline
   forks a flight exactly the way an ungrounded time does. Same pattern, same
   function, third field.
3. **Accept `"Multiple airlines"`.** Checked before assuming: it appears 8
   times in the captured body and is **Kayak's own row label** for
   multi-carrier self-transfer itineraries, not a model invention. The row is
   honest. It cannot merge with Google's named carrier, so such flights will
   show twice — that is a display consequence of truthful data, and inventing
   a carrier to force a merge would be strictly worse. Reconstructing the real
   carriers from the layover detail is speculative and out of scope.
4. **Scope discipline.** No changes to the evasion bundle, the currency
   picker, `make_flight_key`, or the model choice. All four are measured and
   settled.

---

## Phase 1 — Strip paid placements from the extraction input

### Intent
Remove advert text before the model ever sees it, so an advert price cannot
be attached to a real itinerary. Out of scope: anything downstream of
extraction.

### Tasks
1.1 `_strip_placements(body_text) -> str` (pure): remove each placement
    block. A block **starts** at the line containing
    `"This is a paid placement from"` and **ends** at the next `"View Deal"`
    line inclusive. Verified against the captured bodies: the disclosure line
    itself carries the price inline, and the price recurs standalone twice
    more inside the block, so dropping the single disclosure line is **not**
    sufficient — the whole span must go.
1.2 Call it from `_results_section` **before** the existing trim, so the
    trimming window and the `_RESULT_MARKERS` counting both operate on
    advert-free text.
1.3 Return the body unchanged when no disclosure line is present — stripping
    is a filter, and a page with no adverts must pass through untouched.
1.4 Leave grounding to run against the **full original body** as it does
    today. Stripping narrows what the model reads; it must not narrow what
    verification checks, or a legitimate price appearing only outside the
    trimmed window would be dropped as ungrounded.

### Files
- Modify: `backend/sources/kayak.py`

### What NOT to touch
- The extraction prompt (Decision 1), `_price_grounded`, `_time_grounded`,
  `_validate`'s existing checks, `_LLM_MODEL`, `_LLM_TIMEOUT_S`.

### Tests
`tests/test_kayak_placements.py` (new — written with this plan):
- `test_strips_the_expedia_placement_block_from_a_real_captured_body`
- `test_placement_price_does_not_survive_stripping` (the €806 that started
  this — all three occurrences)
- `test_genuine_result_rows_survive_stripping` (€654 and the `Select`
  markers must remain; result-marker count unchanged)
- `test_strips_every_placement_not_just_the_first` (the car-rental adverts
  further down the same page)
- `test_body_without_placements_is_returned_unchanged`
- `test_search_does_not_extract_a_placement_price` (end-to-end through
  `search()`, the actual defect)

### Success criteria
All pass; full suite green.

### Verification
```bash
pytest tests/test_kayak_placements.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/020-phase-1.md`.

---

## Phase 2 — Ground the airline component of the identity

### Intent
Close the last ungrounded component of `flight_key`.

### Tasks
2.1 `_airline_grounded(airline, body_text) -> bool` (pure): the extracted
    carrier must appear in the rendered page. Compare after the same
    normalisation `make_flight_key` applies (casefold, collapse whitespace)
    so a pure case difference is not treated as a fabrication.
2.2 Wire into `_validate` next to `_price_grounded` and `_time_grounded` —
    same drop-and-log-at-`WARNING` behaviour.
2.3 Must keep `"Multiple airlines"` (Decision 3 — Kayak prints it) and must
    keep the first carrier of a comma-joined label such as
    `"Arajet, Iberia"`, since `_first_carrier` already reduces those and the
    substring is genuinely present.

### Files
- Modify: `backend/sources/kayak.py`

### Tests
`tests/test_kayak_placements.py` (same file):
- `test_validate_drops_row_whose_airline_is_absent_from_rendered_text`
- `test_validate_keeps_the_multiple_airlines_label_the_page_prints`
- `test_validate_keeps_the_first_carrier_of_a_comma_joined_label`
- `test_validate_keeps_airline_differing_only_in_case_from_the_page`

### Success criteria
All pass; full suite green; no existing test weakened.

### Verification
```bash
pytest tests/test_kayak_placements.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/020-phase-2.md`.

---

## Phase 3 — Re-enable and watch one cycle

### Intent
Confirm on live data that adverts no longer reach the price table, and that
nothing legitimate was lost to the two new filters.

### Tasks
3.1 Re-enable Kayak on tracker 20 (`PATCH /trackers/20/toggle-kayak`) — it
    should be **off** while Phases 1-2 are in flight.
3.2 Run one cycle. Confirm: no stored row carries a price that appears only
    inside a placement block; the genuine cheapest is still captured; row
    count per run is unchanged from Phase 4's five.
3.3 Re-check tracker 20's all-time low against a hand render, as plan 019
    task 6.6 did.
3.4 Spot-check the captured body for placements the start/end rule missed —
    Kayak may format some placements differently from the three seen so far.

### Success criteria
One clean cycle with adverts absent from stored rows and the real fare still
present.

### Verification
Observations into `.agent/reports/020-phase-3.md`.

---

## Follow-up, explicitly out of scope

- **Headline price oscillation.** The €654 fare exists only on Kayak, so the
  displayed price swings 654 ↔ 800 with Kayak's success rate. This is the
  price-level form of the new/missing churn plan 019 already deferred, and it
  needs the same fix: per-source success recorded on each snapshot, so the UI
  can distinguish "this fare is gone" from "the source that sees it did not
  run this cycle".
- **Multi-carrier merging.** Per Decision 3, `"Multiple airlines"` rows will
  not merge with Google's. Revisit only if it proves noisy in practice.
