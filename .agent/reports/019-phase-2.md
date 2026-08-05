# Plan 019 — Phase 2 report

## Deviation from the brief, up front

**The Phase 2 tests did not exist.** Commit `40754e6` ("Add plan 019 and its
fail-first tests") added only the *Phase 1* tests — `tests/test_kayak_currency.py`
and the `test_kayak_samples.py` addition. Nothing in `tests/test_fingerprint.py`
or `tests/test_kayak_source.py` covered Phase 2. I wrote them fail-first from
the plan's own Tests section before touching implementation, and confirmed
14 failures for real reasons (not import errors) first.

## What I built

**2.1 `make_flight_key` → `airline|departure_time|arrival_time`**
(`backend/fingerprint.py`). `flight_number` is gone from identity and remains a
display-only field.

**2.2 Airline normalisation** — `" ".join(airline.split()).casefold()`.
Verified against the real strings both sources emit before choosing it, as the
task required:

- The production table holds **40 distinct airline values**, 0 non-ASCII,
  0 with internal double-spaces, 0 with leading/trailing whitespace, and
  **0 case-collision groups** — the two existing sources (`google_flights`,
  `fast_flights`) agree exactly, because they share an upstream.
- The collision is real on the **Kayak** side: Kayak prints `GOL` where Google
  prints `Gol`, and `TAP AIR PORTUGAL` where Google prints `Tap Air Portugal`.
  Confirmed in the captured bodies *and* in live extraction output during
  Part B. Casefolding merges these correctly.

**2.3 Kayak stops emitting invented flight numbers.** The prompt now states the
list view has none and requires `null`; `_clean_flight_number` normalises
`"N/A"`/`"unknown"`/`"-"`/`None` to `""`. Confirmed against the live model:
every extracted row came back `flight_number: None`.

**2.4 Production backfill** — executed after explicit confirmation. See below.

**2.5 Dedup re-verification** — all seven sites re-checked, one real defect
found and fixed. See below.

### Not in the plan, added: timestamp canonicalisation

Live extraction during Part B returned the **same physical flight** as
`2026-10-04T00:30` on one attempt and `2026-10-04T00:30:00` on the next. Both
timestamps are now two thirds of the identity key, so this fragments one flight
across runs — precisely the defect this phase exists to remove, reappearing
through a different field, and it would have made Phase 3's task 3.2 ("confirm
the same physical flight yields the same key across attempts") fail.

`KayakSource._canonical_timestamp` runs both values through
`datetime.fromisoformat().isoformat()`, which is also exactly what
`GoogleFlightsSource` emits — so this is what makes the two sources' keys line
up in practice. Unparseable values pass through untouched.

I judged this in scope because Phase 2's stated intent is "one identity **across
sources and across runs**", and it is contained to the source (no key-format
change, no backfill — no Kayak rows exist yet). Flagging it explicitly rather
than folding it in silently.

## Task 2.4 — production backfill

The plan's SQL was **corrected before running** (and the plan itself updated in
`ddd20de`): it concatenated the **raw** airline while 2.2 normalises it, so every
backfilled row would have disagreed with the keys the running code generates —
detaching history rather than preserving it.

Per the user's direction, the backfill was done in **Python calling
`make_flight_key` directly** (`scripts/backfill_019_flight_keys.py`) rather than
hand-written SQL: equivalence by construction, not by coincidence.

Dry run against a full copy first:

```
rows read:      165884
already correct:    228          <- written live since the code edit landed
to rewrite:     165656
null/empty keys after: 0
distinct keys after:   1974
rows where Python key != SQL LOWER(TRIM()) expression: 0
```

Pre-flight checks (all re-confirmed, not assumed):

| Check | Plan said | Actual |
|---|---|---|
| total rows | 165,574 | **165,884** (collection ongoing) |
| empty `departure_time` | 29 | **39** |
| `airline` / `departure_time` / `arrival_time` IS NULL | — | 0 / 0 / 0 |
| distinct airlines | — | 40, all ASCII, no odd whitespace |

Production run:

```
$ docker compose stop
$ cp data/airfare.db data/airfare.db.bak-019
$ docker compose run --rm --entrypoint python airfare-monitor \
      /app/scripts/backfill_019_flight_keys.py /app/data/airfare.db
rows read:      165884
already correct:    228
to rewrite:     165656
null/empty keys after: 0
distinct keys after:   1974
$ docker compose start
```

Post-backfill state:

```
total rows              165923
rows NOT in new format  0
null/empty keys         0
distinct keys           1974
```

```
$ sqlite3 data/airfare.db "SELECT flight_key FROM flight_prices LIMIT 3;"
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
```

**Backup: `data/airfare.db.bak-019` (183,521,280 bytes).**

### Chart lines span full history (the plan-017 precedent check)

Loaded real tracker detail pages and compared each series' extent against the
tracker's actual snapshot range. No break at the code-edit boundary:

```
--- tracker 20: 13 chart series          (68 snapshots, 08-03 20:10 -> 08-05 15:45)
    Iberia IB 272+IB 1287          44 pts  2026-08-04T11:51 -> 2026-08-05T15:45
    ITA AZ 675+AZ 572              47 pts  2026-08-03T20:10 -> 2026-08-05T15:45
--- tracker 26: 13 chart series          (66 snapshots, 08-03 20:16 -> 08-05 15:45)
    Tap Air Portugal TP 88+TP      65 pts  2026-08-03T20:16 -> 2026-08-05T15:45
    United UA 844+UA 3             65 pts  2026-08-03T20:16 -> 2026-08-05T15:45
    KLM KL 792+KL 1923             65 pts  2026-08-03T20:16 -> 2026-08-05T15:45
```

Series reach back to each tracker's **first** snapshot. Labels still show flight
numbers (`Tap Air Portugal TP 88+TP 930`) — correct: `flight_number` remains a
display field.

## Task 2.5 — dedup re-verification, and a real defect

**The merge rate changed far more than "some rows may collapse" suggests.**
Measured on production data:

| | within-snapshot colliding groups | extra rows merged |
|---|---|---|
| old key | 570 | 570 |
| new key | **8,754** | **15,441** |

That is ~9.3% of all rows now sharing a key with another row in the same
snapshot — a **27x** increase. Distinct keys fell 2,535 → 1,974.

Worth recording *what* collides, because it is not only cross-source merging:
multi-stop itineraries that share airline, departure and arrival but route
differently through **different middle legs**. Real example, one snapshot:

```
Air Canada  AC 91+AC 410+AC 874  21:35 -> 07:05  $1414
Air Canada  AC 91+AC 416+AC 874  21:35 -> 07:05  $2430
```

2,232 of the 8,754 groups contain more than one distinct price; the rest are
identical-price duplicates. Option C reduces option B's collision case but does
not eliminate it. The system behaves correctly under this (cheapest-first wins
everywhere), but it is a consequence the plan costed only qualitatively.

### All seven sites re-verified

| Site | Mechanism | Verdict |
|---|---|---|
| `previous_prices` (`pages.py:350`) | `setdefault` over `ORDER BY price ASC` | OK |
| `prev_flights` (`pages.py:351`) | `setdefault` | OK |
| `current_flight_map` (`pages.py:401`) | `setdefault` | OK |
| `ordered_top_keys` (`pages.py:445`) | `_seen_top_keys` dedupe | OK |
| `all_flights` (`pages.py:478`) | `_seen_all_flight_keys` dedupe | OK |
| `get_sticky_top_flight_keys` (`db.py:467`) | `GROUP BY snapshot_id, flight_key` + `MIN(price)` + `SELECT DISTINCT` | OK |
| `history_by_key` (`pages.py:419`) | merge by `(flight_key, snapshot_id)` | **defect found** |

**The defect:** `history_by_key` collapses same-snapshot rows by comparing each
row against `points[-1]` only — it requires same-snapshot rows for a key to
arrive **adjacent**. `get_price_history` ordered by `s.searched_at ASC` alone,
and `searched_at` is second-resolution, so two snapshots sharing a timestamp
could interleave and mis-merge. The code comment states this invariant; the
query never guaranteed it.

Latent before (570 collisions, 0 timestamp ties in production today), but this
phase made a key repeating within a snapshot 27x more likely — so a future tie
would now land on colliding rows rather than passing harmlessly through.

Fix: `ORDER BY s.searched_at ASC, fp.snapshot_id ASC` (`backend/db.py:273`).
No behaviour change absent ties; deterministic tiebreak.

Pinned by a new test,
`test_two_snapshots_sharing_a_timestamp_stay_two_points_with_a_repeated_key`.
**Confirmed non-vacuous**: reversing the tiebreak to `DESC` makes it fail
(`assert [300.0, 100.0] == [100.0, 300.0]`).

## Vacuous-test audit

Checked explicitly, since a currency test had just been caught passing over an
empty list:

- Every new `test_fingerprint.py` assertion compares non-empty strings — no
  collection can be empty.
- `test_map_result_*` assert scalar equality.
- `test_extraction_prompt_states_the_list_view_has_no_flight_numbers` reads
  `captured["messages"]`; if `_extract` never called the client this raises
  `KeyError` rather than passing.
- The new chart-data test asserts `datasets` and `series` are non-empty
  **before** indexing, and was verified to fail under a deliberately broken
  ordering.
- Swept the rest of the suite for `assert all(...)` / `== []` patterns. The
  survivors (`test_chart_colors.py:47`, `test_kayak_scheduling.py:161`) iterate
  collections that are non-empty by construction.
- Removed obsolete tests rather than letting them rot into vacuity:
  `test_nonstop_key_contains_airline_and_flight_number` and
  `test_multistop_key_joins_flight_numbers_with_plus` asserted on the key's
  flight-number segment, which no longer exists.
  `test_flight_key_still_differs_for_genuinely_different_flights_from_same_source`
  distinguished two flights **by flight number alone** — under the new scheme
  those are correctly the same flight, so keeping it would have meant asserting
  the opposite of this phase's purpose. Replaced with
  `test_flight_key_still_separates_genuinely_different_airlines`.

## Verification

```
$ docker exec airfare-monitor pytest tests/test_fingerprint.py tests/test_kayak_source.py -v
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
collected 67 items

tests/test_fingerprint.py::test_flight_key_has_three_parts_of_airline_and_both_times PASSED [  1%]
tests/test_fingerprint.py::test_flight_key_excludes_flight_number PASSED  [  2%]
tests/test_fingerprint.py::test_flight_key_does_not_start_with_source_name PASSED [  4%]
tests/test_fingerprint.py::test_flight_key_is_unchanged_by_the_flight_number_field PASSED [  5%]
tests/test_fingerprint.py::test_multistop_key_keeps_the_joined_airline_segment PASSED [  7%]
tests/test_fingerprint.py::test_same_flight_result_produces_same_key_on_repeated_calls PASSED [  8%]
tests/test_fingerprint.py::test_different_departure_times_produce_different_keys PASSED [ 10%]
tests/test_fingerprint.py::test_flight_key_differs_for_same_airline_and_departure_but_different_arrival PASSED [ 11%]
tests/test_fingerprint.py::test_flight_key_normalises_airline_casing_and_whitespace PASSED [ 13%]
tests/test_fingerprint.py::test_flight_key_still_separates_genuinely_different_airlines PASSED [ 14%]
tests/test_fingerprint.py::test_flight_key_matches_across_sources_when_one_lacks_a_flight_number PASSED [ 16%]
tests/test_fingerprint.py::test_flight_key_identical_across_different_sources_for_same_physical_flight PASSED [ 17%]
tests/test_fingerprint.py::test_key_with_empty_airline_still_produces_three_parts PASSED [ 19%]
tests/test_fingerprint.py::test_key_with_empty_airline_still_differs_by_departure_time PASSED [ 20%]
tests/test_fingerprint.py::test_key_with_empty_departure_time_still_produces_three_parts PASSED [ 22%]
tests/test_kayak_source.py::test_kayak_source_satisfies_search_source_protocol PASSED [ 23%]
tests/test_kayak_source.py::test_build_url_includes_origin_destination_and_date PASSED [ 25%]
tests/test_kayak_source.py::test_build_url_sorts_by_cheapest_price PASSED [ 26%]
tests/test_kayak_source.py::test_build_url_encodes_requested_currency PASSED [ 28%]
tests/test_kayak_source.py::test_looks_blocked_true_when_captcha_marker_present PASSED [ 29%]
tests/test_kayak_source.py::test_looks_blocked_false_for_normal_results_page PASSED [ 31%]
tests/test_kayak_source.py::test_looks_blocked_false_for_empty_string PASSED [ 32%]
tests/test_kayak_source.py::test_looks_blocked_true_for_real_kayak_interstitial PASSED [ 34%]
tests/test_kayak_source.py::test_looks_blocked_true_for_perimeterx_press_and_hold_challenge PASSED [ 35%]
tests/test_kayak_source.py::test_looks_blocked_false_for_long_results_page_mentioning_humans PASSED [ 37%]
tests/test_kayak_source.py::test_search_returns_flight_results_mapped_from_extraction PASSED [ 38%]
tests/test_kayak_source.py::test_search_sets_source_field_to_kayak_on_every_result PASSED [ 40%]
tests/test_kayak_source.py::test_search_result_currency_matches_requested_currency PASSED [ 41%]
tests/test_kayak_source.py::test_search_returns_empty_list_and_error_when_render_raises PASSED [ 43%]
tests/test_kayak_source.py::test_search_returns_empty_list_and_warning_when_blocked_markers_detected PASSED [ 44%]
tests/test_kayak_source.py::test_search_returns_empty_list_and_error_when_extraction_raises PASSED [ 46%]
tests/test_kayak_source.py::test_search_returns_empty_list_and_warning_when_extraction_finds_no_flights PASSED [ 47%]
tests/test_kayak_source.py::test_search_with_top_n_zero_returns_empty_list_without_rendering PASSED [ 49%]
tests/test_kayak_source.py::test_search_never_raises_for_unexpected_exception_type PASSED [ 50%]
tests/test_kayak_source.py::test_search_maps_result_with_missing_optional_fields_without_crashing PASSED [ 52%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[N/A] PASSED [ 53%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[n/a] PASSED [ 55%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[unknown] PASSED [ 56%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[Unknown] PASSED [ 58%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[-] PASSED [ 59%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[] PASSED [ 61%]
tests/test_kayak_source.py::test_map_result_normalises_placeholder_flight_numbers_to_empty[None] PASSED [ 62%]
tests/test_kayak_source.py::test_map_result_keeps_a_genuine_flight_number PASSED [ 64%]
tests/test_kayak_source.py::test_extraction_prompt_states_the_list_view_has_no_flight_numbers PASSED [ 65%]
tests/test_kayak_source.py::test_map_result_canonicalises_timestamps_missing_seconds PASSED [ 67%]
tests/test_kayak_source.py::test_same_flight_yields_one_key_whether_or_not_seconds_were_emitted PASSED [ 68%]
tests/test_kayak_source.py::test_map_result_leaves_an_unparseable_timestamp_untouched PASSED [ 70%]
tests/test_kayak_source.py::test_validate_drops_row_whose_price_is_absent_from_body_text PASSED [ 71%]
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_appears_thousands_separated PASSED [ 74%]
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_uses_dot_thousands_separator PASSED [ 75%]
tests/test_kayak_source.py::test_validate_keeps_row_whose_price_uses_comma_decimals PASSED [ 77%]
tests/test_kayak_source.py::test_validate_drops_non_positive_price PASSED [ 78%]
tests/test_kayak_source.py::test_validate_drops_price_wildly_outside_the_band_of_other_rows PASSED [ 80%]
tests/test_kayak_source.py::test_search_drops_hallucinated_price_not_present_in_rendered_text PASSED [ 81%]
tests/test_kayak_source.py::test_search_warns_when_validation_drops_every_row PASSED [ 83%]
tests/test_kayak_source.py::test_search_reports_dropped_row_count_when_some_rows_survive_validation PASSED [ 84%]
tests/test_kayak_source.py::test_error_message_does_not_contain_api_key PASSED [ 86%]
tests/test_kayak_source.py::test_results_section_keeps_only_the_requested_number_of_itineraries PASSED [ 87%]
tests/test_kayak_source.py::test_results_section_keeps_the_first_itinerary_intact PASSED [ 89%]
tests/test_kayak_source.py::test_results_section_drops_page_chrome_around_the_results PASSED [ 90%]
tests/test_kayak_source.py::test_results_section_recognises_localized_action_buttons PASSED [ 92%]
tests/test_kayak_source.py::test_results_section_returns_body_unchanged_when_no_markers_found PASSED [ 93%]
tests/test_kayak_source.py::test_results_section_returns_body_unchanged_for_non_positive_top_n PASSED [ 95%]
tests/test_kayak_source.py::test_results_section_handles_fewer_results_than_requested PASSED [ 96%]
tests/test_kayak_source.py::test_extract_disables_model_thinking PASSED  [ 98%]
tests/test_kayak_source.py::test_extract_states_the_departure_date_in_the_prompt PASSED [100%]

======================= 66 passed, 1 deselected in 1.77s =======================

$ docker exec airfare-monitor pytest tests/ -v -k "not slow"
[... 363 lines ...]
====================== 363 passed, 3 deselected in 25.53s ======================

$ sqlite3 data/airfare.db "SELECT flight_key FROM flight_prices LIMIT 3;"
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
aegean|2026-07-29T11:35:00|2026-07-30T01:00:00
```

Suite went 346 → 363 (+17: 4 fingerprint, 12 kayak_source, 1 chart_data).

## Live-service verification (Active dev — edits deploy instantly)

```
$ docker compose ps
airfare-monitor   Up (healthy)   0.0.0.0:8100->8100/tcp

$ # one real search_and_store
snapshot before: 6325 2026-08-05 15:45:17
snapshot after:  6328 2026-08-05 15:46:05 rows= 6
new snapshot created: True
    tap air portugal|2026-08-20T20:45:00|2026-08-21T22:30:00 | fast_flights 707.0
    tap air portugal|2026-08-20T15:30:00|2026-08-21T12:25:00 | fast_flights 814.0
    united|2026-08-20T22:20:00|2026-08-22T07:45:00 | fast_flights 872.0
    klm|2026-08-20T21:45:00|2026-08-21T16:45:00 | fast_flights 917.0

$ # pages
/              HTTP 200  91084 bytes
/monitor       HTTP 200  251006 bytes
/trackers/26   HTTP 200  49890 bytes

$ # system_logs — no errors
INFO  search_done   26  6 results
INFO  search_start  26
INFO  search_done   27  7 results
INFO  search_done   21  6 results
```

**Tracker 20 remained `kayak_enabled=0` throughout, as did every other tracker**
(verified after all work: `SELECT id FROM trackers WHERE kayak_enabled <> 0` →
empty).

## Open issue for Phase 3 — multi-carrier airline names do not merge

Confirmed in **live extraction output**, not inferred:

```
'Azul, easyJet'            <- Kayak
'Azul, TAP AIR PORTUGAL'   <- Kayak
```

`GoogleFlightsSource` sets `airline` from `primary_airline_name` — a **single**
carrier — while Kayak's list view prints a comma-joined list for multi-carrier
itineraries. Casefolding cannot bridge this: `azul, easyjet` will never equal
`azul`.

Consequence: single-carrier flights merge across sources correctly (`GOL`↔`Gol`
verified), but **multi-carrier Kayak rows will not merge with their Google
counterparts** — they will appear as Kayak-exclusive, and churn new/missing on
every failed Kayak run.

This is a **design decision, not an implementation detail** (take the first
carrier? map to a primary? keep a separate display field?), so I have not
improvised a fix — same reasoning that kept the currency conversion layer out of
Part B. It belongs in the plan before Phase 3 measures key stability, since
task 3.2 will otherwise report a stability failure that is really this.

## Follow-ups / noted, not done

- **Multi-carrier airline merge** — above. Needs a plan decision.
- **LLM latency tail is worse than Decision 3 measured.** Isolated against a
  captured body (no Kayak request): 5.5s / **30.0s timeout** / 3.5s across three
  consecutive calls, plus two consecutive `search()` timeouts before a success.
  Decision 3 recorded 1-in-6; today looked closer to 1-in-3. Decision 3 says
  observe rather than raise the cap — still the right call, but Phase 3 should
  treat this as a measurement target, not background noise.
- **`_OVERALL_TIMEOUT_S` does not account for the warm-up navigation.** It is
  derived as `2 * _RENDER_TIMEOUT_S + _LLM_TIMEOUT_S + 30`, but `_render` also
  performs a warm-up `goto` plus a 2-5s dwell before the real navigation. Worst
  case exceeds the budget. Not hit today (renders ran ~29-60s); flagged because
  CLAUDE.md explicitly says to re-check this arithmetic.
- **Xvfb stale-lock bug — found and fixed.** See the companion report.

## Confidence

**good** — every plan task is done and independently verified; the backfill was
dry-run against a full copy, cross-validated two ways, and confirmed on the live
page; the one defect found in 2.5 is fixed and its test proven non-vacuous. The
multi-carrier issue is disclosed rather than papered over.
