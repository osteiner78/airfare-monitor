# Plan 021 Phase 3 — the cycle plan 020 never got

**Both success criteria met.** Two successful in-app cycles — one forced, one
scheduled — adverts absent, real fares present, no row-count drop.

**Plan 020 Phase 3 is complete.** Its tasks 3.2-3.5 ran here for the first
time; `.agent/reports/020-phase-3.md` recorded them as blocked/inconclusive
because `_render` never once succeeded through the deployed path.

## 3.1 — forced cycle via `POST /api/trackers/20/search`

Deliberately in-app: this is the path with a 7-for-7 (then 12-for-12) failure
record. `kayak_next_due_at` was set to `NULL` beforehand to make Kayak due —
the same operational column the scheduler itself writes each cycle.

```
fired 03:47:33 UTC   http=200   total=375.8s
snapshot 6789 @ 03:53:49   rows=116   kayak=5
logs: 13725 INFO search_start / 13726 INFO search_done "116 results"
```

No `kayak_search_error`, no WARNING, no ERROR. 375.8s = ~4 min of the 0-15 min
anti-detection jitter, plus render, plus extraction.

**This is the first Kayak render this project has ever completed through the
production path.**

| | airline | price | departure | arrival |
|---|---|---|---|---|
| 1 | Arajet | €706 | 2026-08-21T03:50 | 2026-08-22T17:10 |
| 2 | Iberia | €797 | 2026-08-21T14:00 | 2026-08-22T11:05 |
| 3 | Multiple airlines | €835 | 2026-08-21T21:15 | 2026-08-22T21:20 |
| 4 | Air Europa | €837 | 2026-08-21T13:50 | 2026-08-22T10:05 |
| 5 | ITA Airways | €854 | 2026-08-21T18:55 | 2026-08-22T16:50 |

**Two cross-source merges**, up from plan 019 Phase 4's one, Kayak cheaper on
both:

```
iberia|2026-08-21T14:00:00|2026-08-22T11:05:00   google €806  kayak €797
air europa|2026-08-21T13:50:00|2026-08-22T10:05:00  google €838  kayak €837
```

(116 rows collapse to 99 distinct `flight_key`s in this snapshot.)

## 3.2 (plan 020) — no advert price stored

Sample `20260810T035349.042796.txt`, 20,051 chars, **10 paid placements**.

```
'This is a paid placement from' lines: 10
'View Deal': 20      '| Ad': 0      'Sponsored': 0
body 20051 -> stripped 16180  (3,871 chars removed)
prices appearing ONLY inside placement blocks: 805, 1,406, 844
```

None of €805 / €1,406 / €844 reached the DB — every stored row has
`price_in_placement_only: False`. **The €805 Expedia block is the same shape
as the original €806 defect** (plan 019 Phase 4): same advertiser, same
"Book your flight to unlock more savings" copy, price welded next to a real
itinerary. It was stripped before `_extract` ever saw it.

Row count **5**, unchanged from Phase 4's five.

## 3.3 (plan 020) — all-time low re-checked

Better than a hand render: the €654 all-time low was re-checked against **the
body captured at the moment it was stored** (`20260806T012940.952907.txt`,
snapshot 6390 @ 01:29:40), by asking whether each price survives
`_strip_placements`:

| price | survives stripping | verdict |
|---|---|---|
| €654 | yes | **organic** |
| €732 | yes | organic |
| €775 | yes | organic |
| €796 | yes | organic |
| €806 | **no** | **ONLY-IN-AD** |

So `_strip_placements` would have caught the original defect on the very body
that produced it, and would have kept all four genuine rows. **The €654
all-time low is genuine**, and the four rows plan 020 Phase 3 chose to keep
were the right four. Retrospective confirmation on the real defect data, which
is stronger evidence than a clean run alone.

€654 no longer exists on the page (the 03:50 Arajet slot now prices at
€705-706), so the "Historical best" badge legitimately shows a fare no current
line reaches — that is the known chart bug in CLAUDE.md, not a data fault.

## 3.4 (plan 020) — placement formats the strip rule might miss

Across both cycles: 10 and 9 disclosure lines, with `View Deal` occurring
exactly **twice per block** (once inline at the end of the disclosure line,
once standalone). That is precisely the shape `_strip_placements`'s
"start search on the line *after* the disclosure" rule was written for, and
all blocks were removed cleanly.

**Not exercised:** `| Ad` and `Sponsored` never appeared (0 occurrences in
both bodies). The `"| Ad"` variant named in CLAUDE.md is still unverified
against live traffic. `Ad` does appear as its own line (10x / 9x) but always
inside a block already bounded by the disclosure/`View Deal` pair, so it needs
no rule of its own today.

## 3.5 (plan 020) — airline grounding dropping legitimate rows

**The risk did not materialise.** Both cycles returned **5 rows, not 4**, and
every airline is grounded:

```
Arajet            grounded=True  literal_in_body=True
Iberia            grounded=True  literal_in_body=True
Multiple airlines grounded=True  (trusted label)
Air Europa        grounded=True  literal_in_body=True
ITA Airways       grounded=True  literal_in_body=True
```

The IATA-code-vs-full-name failure mode (the `"LX"` vs `"SWISS"` fixture
problem) **did not occur**: the model returned full names exactly as printed.
No WARNING naming a dropped airline appeared in `system_logs` at any point.

Also confirmed working: the page prints `Arajet, Air Europa` for the
multi-carrier itinerary and the stored row is `Arajet` — `_first_carrier`
taking the text before the first comma, as designed.

This is **absence of the failure, not proof it cannot happen.** Two cycles on
one route is a small sample, and the tell (a silent drop to four rows plus a
WARNING) remains worth watching. The fix if it appears is still prompt-side.

## 3.3 (plan 021) — a natural scheduler cycle

To avoid a 3-hour wait, tracker 20's `interval_minutes` was temporarily set to
**20** (`PATCH /api/trackers/20`, which re-registers the APScheduler job), and
`kayak_next_due_at` cleared after the re-registration's immediate run so the
*next unattended tick* would own the Kayak call.

```
03:55:18  interval -> 20, job re-registered
03:55:19  snapshot 6790  rows=109  kayak=0   (immediate run; Kayak not due -- correct)
04:15:18  natural tick fires (unattended, scheduler-driven)
04:30:17  snapshot 6791  rows=114  kayak=5   (~15 min jitter, then render + extract)
```

No errors, no warnings. Same five flight_keys as the forced cycle, prices
within €1 (Arajet €706 -> €705 — real movement, and evidence the identity is
stable across runs rather than re-forking). Placement handling identical:
9 blocks, same three placement-only prices, none stored.

`interval_minutes` has been **restored to 180**.

## State changes made, and their restoration

| Change | Restored? |
|---|---|
| `kayak_next_due_at` set to NULL twice (to make Kayak due) | n/a — scheduler owns this column; now `2026-08-10 04:48:10` |
| `interval_minutes` 180 -> 20 | **yes, back to 180** |
| `active` / `kayak_enabled` | never changed (both remain 1) |

Three extra Google-only snapshots (6790 plus two re-registration runs) were
created as a side effect of re-registering the job — genuine price data, no
corruption. No DB rows were deleted and no schema was touched.

**Also worth recording:** during the Phase 1/2 root-cause work, each edit to
`backend/main.py` reloaded the worker, and the lifespan re-registers tracker
jobs with `run_immediately=True` — so ~122 snapshots were created across all
trackers between 02:00 and 04:00, well above the normal rate. All are real
Google Flights data; the cost was extra upstream requests, not bad data. Worth
knowing before doing heavy `--reload` debugging on this service again.

## Success criteria

- [x] Two successful in-app cycles, one forced (6789) and one scheduled (6791)
- [x] Adverts absent from stored rows in both
- [x] The real fare present in both (5 rows each, cheapest €706 / €705)
- [x] No unexplained row-count drop (5 both times, matching Phase 4)
- [x] Plan 020 Phase 3 marked complete

## Follow-ups

- **`| Ad` / `Sponsored` placement variants remain unverified live** (3.4).
- **Airline grounding is unproven, not disproven** (3.5) — two cycles, one
  route. Keep watching for a four-row run.
- **Headline price oscillation** (carried from plan 020, still out of scope):
  the €654 fare no longer exists, so today the displayed best price tracks the
  €705-706 Arajet fare, which Kayak alone sees. Needs per-source success
  recorded per snapshot.
- **The chart bug in CLAUDE.md is now visibly live on tracker 20**: the
  "Historical best" badge shows €654 while no chart line reaches it, because
  `filters.js` drops sticky-but-missing flights. Unchanged by this plan.

## Confidence

**Certain** on both cycles and all four plan 020 checks — each is a direct
observation with the stored rows, the captured body, and the log table all
agreeing, plus the retrospective €806/€654 result on the original defect body.

**Likely-good** on durability: the mechanism is understood and fixed rather
than worked around, but this is two cycles on one route over ~40 minutes.
