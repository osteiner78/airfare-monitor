# 024 Phase 4 — airline identity (the only data migration)

**Plan:** `.agent/plans/024-code-review-remediation.md`, Phase 4
**Date:** 2026-08-13
**Commit:** `d23d5a8`
**Confidence:** likely-good (see "Live verification" — the live-cycle half of
the plan's verification is blocked by an external quota, not by this change)

---

## What was built

**Task 4.1 — `backend/airlines.py`.** Moved `_AIRLINE_NAME_TO_CODE` (61 entries)
out of `pages.py` into a new leaf module with no project imports, exported as
`AIRLINE_NAME_TO_CODE`. `pages.py` now does `from backend.airlines import
AIRLINE_NAME_TO_CODE` and keeps `_AIRLINE_NAME_TO_CODE` as an alias, so its two
existing consumers (`_airline_code_from_name` for the logo, `_airline_identity`
for the facet grouping) are untouched. The module docstring records why it is a
leaf: `fingerprint.py` cannot import `pages.py`, and that import direction is
why the identity and the facet normalisations diverged.

**Task 4.2 — `_normalize_airline` consults the map.** Whitespace is collapsed,
the upper-cased name is looked up, and the result (code if mapped, the name
otherwise) is casefolded. Mapped carriers key as `la|dep|arr`; unmapped names
(Kayak's `Multiple airlines`, `Aerolineas Argentinas`) keep the pre-existing
casefolded form.

**Task 4.3 — the gated backfill.** Backed up and re-ran
`scripts/backfill_019_flight_keys.py` against production with the container
stopped, per the script's own docstring and the plan 019 precedent. **Approved
explicitly by the user before running** (the plan's stated gate); the user chose
the stop-container option over the live-DB one.

---

## Verification

### Full suite — after the code change

```
$ docker exec airfare-monitor python -m pytest tests/ -q -k "not slow"
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 43%]
........................................................................ [ 57%]
........................................................................ [ 72%]
........................................................................ [ 86%]
....................................................................     [100%]
500 passed, 3 deselected in 298.18s (0:04:58)
```

Baseline immediately before the change, same command: `482 passed, 3 deselected
in 300.80s`. The delta is exactly the 18 tests added by this phase (9 of them
parametrised pairs). **No pre-existing test was modified, weakened, skipped or
deleted** — in particular every assertion in `tests/test_fingerprint.py` still
holds unchanged, including `airline="LX"` → `parts[0] == "lx"` (`LX` is a *code*,
not a map key, so it is unmapped and passes through) and
`"LH+OS"` → `"lh+os"`.

### The new tests failing first, for the right reason

```
$ docker exec airfare-monitor python -m pytest tests/test_airline_identity.py -q
ImportError while importing test module '/app/tests/test_airline_identity.py'.
tests/test_airline_identity.py:17: in <module>
    from backend.airlines import AIRLINE_NAME_TO_CODE
E   ModuleNotFoundError: No module named 'backend.airlines'
```

The two behavioural assertions the plan names were then confirmed red against
the pre-change `_normalize_airline` before the module landed (`latam` !=
`latam airlines`), and green after.

### Focused run

```
$ docker exec airfare-monitor python -m pytest tests/test_airline_identity.py \
    tests/test_fingerprint.py tests/test_filters.py tests/test_airline_logo.py -v
...
70 passed in 6.69s
```

### Backfill — dry run, then the migration

Read-only impact check before touching anything:

```
rows total          246986
rows to rewrite     237063
distinct keys now   2198
distinct keys after 2193
```

237k rows change because nearly every airline name is in the map — that is an
opaque-identifier rename (`iberia` → `ib`), not a data change. The **5** merged
identities are the real content of the migration.

```
$ docker compose stop
 Container airfare-monitor Stopped
$ cp data/airfare.db data/airfare.db.bak-024-phase4
$ sqlite3 data/airfare.db.bak-024-phase4 "PRAGMA integrity_check;"
ok
$ python3 scripts/backfill_019_flight_keys.py data/airfare.db
rows read:      246986
already correct:   9923
to rewrite:     237063
null/empty keys after: 0
distinct keys after:   2193
python3 scripts/backfill_019_flight_keys.py data/airfare.db  4.865 total
$ sqlite3 data/airfare.db "PRAGMA integrity_check;"
ok
```

The named forked pairs, post-backfill, in the exact snapshots the plan's
verification table cites:

```
snapshot_id  flight_key                                  airlines                           srcs                  n
-----------  ------------------------------------------  ---------------------------------  --------------------  -
7116         az|2026-08-21T14:15:00|2026-08-22T10:05:00  ITA Airways,ITA                    kayak,google_flights  2
7116         tp|2026-08-21T00:45:00|2026-08-21T22:30:00  TAP AIR PORTUGAL,Tap Air Portugal  kayak,google_flights  2
7117         la|2026-08-21T21:15:00|2026-08-22T19:10:00  LATAM Airlines,LATAM               kayak,google_flights  2
7117         la|2026-08-21T21:15:00|2026-08-22T22:25:00  LATAM Airlines,LATAM               kayak,google_flights  2
7118         la|2026-08-21T18:20:00|2026-08-22T10:35:00  LATAM,LATAM Airlines               google_flights,kayak  2
7122         la|2026-08-21T21:15:00|2026-08-22T19:10:00  LATAM Airlines,LATAM               kayak,google_flights  2
7124         la|2026-08-21T18:20:00|2026-08-22T10:35:00  LATAM,LATAM Airlines               google_flights,kayak  2
7238         la|2026-08-21T18:20:00|2026-08-22T10:35:00  LATAM,LATAM Airlines               google_flights,kayak  2
7242         la|2026-08-21T18:20:00|2026-08-22T10:35:00  LATAM,LATAM Airlines               google_flights,kayak  2
```

(The `tp` row is the TAP pair the plan's "Corrections" section notes was
*already* bridged by casefolding — it appears here because the key was renamed,
not because anything merged.)

### "One chart line where two existed" — before vs after, same itinerary

Backup DB (pre-backfill) and live DB (post-backfill), tracker 22, one physical
itinerary:

```
=== data/airfare.db.bak-024-phase4 ===
flight_key                                              srcs            airlines        points
------------------------------------------------------  --------------  --------------  ------
finnair|2026-08-21T18:20:00|2026-08-22T10:35:00         kayak           Finnair         29
latam airlines|2026-08-21T18:20:00|2026-08-22T10:35:00  kayak           LATAM Airlines  29
latam|2026-08-21T18:20:00|2026-08-22T10:35:00           google_flights  LATAM           132

=== data/airfare.db ===
flight_key                                  srcs                  airlines              points
------------------------------------------  --------------------  --------------------  ------
ay|2026-08-21T18:20:00|2026-08-22T10:35:00  kayak                 Finnair               29
la|2026-08-21T18:20:00|2026-08-22T10:35:00  google_flights,kayak  LATAM,LATAM Airlines  161
```

And the same thing as the **rendered page** actually serves it:

```
$ (parse window.chartData from GET /trackers/22)
total chart datasets: 28
datasets for the merged key: 1
  label: LATAM LA 8068 | points: 132
old-format latam keys still charted: []
```

132 points from 161 rows is correct, not a loss: those 161 rows span 132
distinct snapshots (`COUNT(*) 161 / COUNT(DISTINCT snapshot_id) 132`), and
`history_by_key` merges chart points by `(flight_key, snapshot_id)` — Kayak
shares fli's snapshot by design, so a snapshot quoted by both sources is one
point.

The remaining `ay` (Finnair) line is a **codeshare**, same times and different
marketing carrier — explicitly out of scope, on the roadmap per the plan's
"023 arch." row.

### Service smoke test after restart

```
$ docker compose start && docker compose ps
airfare-monitor   Up 12 seconds (healthy)   0.0.0.0:8100->8100/tcp
GET / -> 200
tracker 20 -> 200
tracker 21 -> 200
tracker 22 -> 200
```

### Live cycle — partially blocked, not by this change

`POST /api/trackers/20/search` completed in 51.6s and stored a snapshot (7258,
116 `google_flights` rows). **Kayak contributed nothing: the extraction LLM
returned HTTP 429.**

```
2026-08-13 04:57:13  INFO   search_done         20  116 results
2026-08-13 04:57:13  ERROR  kayak_search_error  20  KayakSource: RateLimitError: Error code: 429 -
    {'type': 'error', 'error': {'type': 'FreeUsageLimitError',
     'message': 'Error from provider (Console): Rate limit exceeded. Please try again later.'}}
```

This is the free-tier quota on the opencode.ai Zen model, and it is
**pre-existing and unrelated to Phase 4** — the same 429 is in `system_logs` at
03:07:44, 03:08:55, 03:16:33, 04:20:46, 04:29:46, 04:36:47 and 04:38:57, i.e.
hours before this phase touched anything, across all three Kayak trackers.
Degradation behaved exactly as designed: the snapshot was still created with
fli's rows and the failure was logged at the source's own level.

Consequence for verification: I could not observe the merge on **freshly
fetched** cross-source rows. The merge is instead evidenced above on stored
rows, on the rendered chart, and by the unit tests. Worth re-checking once the
quota resets — the tell is a Kayak-bearing snapshot whose `LATAM Airlines` row
shares a key with the same cycle's `google_flights` `LATAM` row.

---

## Deviations from the plan

1. **`pages.py` keeps the name `_AIRLINE_NAME_TO_CODE` as an alias** for the
   imported object rather than every use site being rewritten. The plan says
   "move it out of `pages.py`"; it is out, and the alias keeps the diff to the
   two lines that matter instead of touching unrelated call sites and the facet
   code Phase 5 is about to rewrite anyway. A test pins that the alias is the
   *same object*, not a copy.
2. **The backfill ran on the host, not in the container.** The container was
   stopped (the user's choice), and the script's import chain
   (`fingerprint` → `airlines` → `sources.base`) is stdlib-only, so no project
   dependencies are needed. Verified by importing it before running.

## Test gaps flagged / new tests added

**The orchestrator wrote no test file for this phase** — the plan specifies
test *scenarios* in prose ("Tests: `make_flight_key(airline="LATAM") ==
make_flight_key(airline="LATAM Airlines")`; broad form over every pair sharing a
map entry"), the same shape as phases 1–3, which the reports for those phases
handled identically. I wrote `tests/test_airline_identity.py` (18 tests) to
match those scenarios and am flagging it here under the skill's
"discovery gap" provision rather than treating the behaviour as covered.

Beyond the two scenarios the plan names, the file pins:

- the **broad form**, parametrised over all 9 variant pairs in the map, plus a
  guard test asserting the parametrisation actually covers ≥5 pairs — otherwise
  reducing the map to one name per code would silently make the broad test
  vacuous;
- that a mapped name normalises to the **code** (`la`), which is the decision
  the plan made against the canonical-name alternative;
- that **unmapped** names keep the old behaviour, including whitespace and case
  collapse — this is the half of `_normalize_airline` that must *not* change;
- that four distinct carriers still get four distinct keys, guarding against a
  map edit that over-merges;
- that `pages` and `fingerprint` hold the **same map object**.

## Follow-ups / noted but not done

- **Kayak extraction is rate-limited right now** (429, free tier, since at least
  03:07 today). Not a Phase 4 concern, but every Kayak tracker is currently
  producing google-only snapshots. Worth a decision separately — it is the same
  free-quota class of problem that moved the model off `deepseek-v4-flash`.
- **The airline map is now load-bearing for identity.** Adding a variant to it
  changes `flight_key` for every row of that carrier, so a map edit now implies
  re-running the backfill. Recorded in CLAUDE.md.
- **Codeshares** (the `ay`/`la` pair above, identical times, different marketing
  carrier) remain a second identity fork. Plan defers this to the roadmap;
  Phase 6 adds the TODO entry.
- `pages.py::_airline_identity` still duplicates the map lookup that
  `_normalize_airline` now performs. Phase 5 rewrites that code for the checkbox
  identity, so collapsing the two is best done there, not here.

## CLAUDE.md updates

- Added `backend/airlines.py` to the project structure block.
- Rewrote the `_normalize_airline` half of the `flight_key` note: the map
  lookup, why the code and not a canonical name, why the module is a leaf, that
  case differences were *always* bridged and only shortened-vs-full names
  forked, and that a map edit now implies a backfill.
- Recorded the 2026-08-13 backfill (237,063 / 246,986 rows, 2198 → 2193 distinct
  keys, backup `data/airfare.db.bak-024-phase4`).
- Noted the SQL shortcut is now *doubly* wrong (it cannot consult the map).
- Test count 456 → 500. (Phase 6 owns the final count; this is the current one.)
