# 025 — Give identity normalisation a home

**Why:** both code reviews (`022` architectural section, `023` A-series) reached
the same conclusion independently: *identity normalisation has no home*. Five
functions across three layers decide what makes two rows the same flight, no
layer is authoritative, and the ordering between them is held by call order
alone. That shape produced two production defects in one week — the
dedupe-before-normalisation bug (`130b205`) and the airline fork (`d23d5a8`) —
both fixed as instances, neither fixed as a class.

**Date:** 2026-08-14
**Constraint that makes this cheap:** verified before starting, this refactor is
**key-preserving** — no backfill, no migration, no data risk.

- `flight_prices` holds **0** airline values containing a comma.
- `flight_prices` holds **0** timestamps outside `YYYY-MM-DDTHH:MM:SS`.

So folding comma-splitting and timestamp canonicalisation into the identity
layer cannot change any stored key. That is a precondition, not an assumption:
Phase 3 re-checks it against all ~246k rows before the work is called done.

---

## The current state

| # | Function | Layer | Decides |
|---|---|---|---|
| 1 | `fingerprint._normalize_airline` | identity | stored key's airline |
| 2 | `pages._airline_identity` | display | facet/checkbox identity |
| 3 | `kayak._first_carrier` | source | stored airline text + key |
| 4 | `kayak._canonical_timestamp` | source | stored timestamps + key |
| 5 | `kayak._rebase_departure_date` | source | which calendar day a time belongs to |

**#1 and #2 are byte-identical logic in two files.** Plan 024 Phase 4 moved the
*data* (`AIRLINE_NAME_TO_CODE`) into a leaf module but left the *function*
duplicated — so the exact divergence that caused the fork is still structurally
possible, just currently in agreement.

**#3 and #4 are source-local normalisations that the identity layer depends on
but cannot see.** If a future source emits `"Azul, easyJet"` or `"...T19:20"`,
its rows fork from Kayak's for the same physical flight, and nothing fails.

---

## The design

`fingerprint.py` becomes the authoritative identity layer and owns every
normalisation that feeds a `flight_key`:

```python
def normalize_airline(airline: str) -> str   # first carrier, whitespace, variant map, casefold
def canonical_timestamp(value) -> str        # ISO round-trip, unparseable passes through
def make_flight_key(result) -> str           # composes the above
```

Every other layer **defers** rather than reimplements:

- `pages._airline_identity` → deleted, calls `normalize_airline`.
- `kayak._canonical_timestamp` → deleted, `_map_result` calls
  `canonical_timestamp`.
- `kayak._first_carrier` **stays** — it shapes the stored *display* value, which
  is a different job from identity. But `normalize_airline` now also splits on
  comma, so identity is correct even for a source that never calls it. Belt and
  braces, deliberately: the display value is a source's business, the identity
  is not.
- `kayak._rebase_departure_date` **stays in Kayak.** It is a source-level repair
  of a page-semantics question ("which calendar day does a printed 00:45 belong
  to?"), not a general normalisation. It must run *before* identity is computed,
  which Phase 2 pins with a test rather than leaving to call order.

**The load-bearing change is `make_flight_key` canonicalising its own inputs.**
Today it trusts callers to have normalised timestamps; after this it cannot be
given a non-canonical value that produces a wrong key. That is what turns "every
source must remember to normalise" into "the identity layer does it".

---

## Phases

### Phase 1 — the identity layer owns it

`fingerprint.py`: rename `_normalize_airline` → `normalize_airline` (public — it
has three consumers now), add comma-splitting, add `canonical_timestamp`, and
have `make_flight_key` route both timestamps through it.

**Tests:** name-variant pairs still agree; `"Azul, easyJet"` and `"Azul"` agree;
`"...T19:20"` and `"...T19:20:00"` agree; unparseable timestamps still pass
through; empty components still produce the 2-separator key the backfill expects.

### Phase 2 — consumers defer

1. `pages.py`: delete `_airline_identity`, import `normalize_airline`.
2. `kayak.py`: delete `_canonical_timestamp`, call the shared one in
   `_map_result`.

**Tests:** the facet identity and the stored key agree for a table of names
(the assertion that would have failed before plan 024 Phase 4 — now it is
structural, not coincidental); rebase → dedupe → map ordering stays pinned.

### Phase 3 — prove it changed nothing

Recompute `make_flight_key` for every row in the production DB with the new code
and assert **zero** differences against the stored key. Read-only; no write, no
backup needed because nothing is written.

This is the gate. A single difference means the refactor was not key-preserving
and must be reverted rather than backfilled — a second identity migration in one
week is not worth a refactor whose entire value is structural.

**Verify:** full suite + the key-invariance script output in
`.agent/reports/025-phase-3.md`.

---

## Out of scope

- `_rebase_departure_date`'s cutoff, `historical_best_price`, and the grounding
  checks are untouched.
- The `airline` *display* column keeps its current values. This changes what
  identity means, not what the user reads.
- No new airline variants are added to the map. Extending that map is a data
  change with its own key consequences and belongs in its own commit.
