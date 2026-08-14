# 025 Phase 3 — verification

**Date:** 2026-08-14
**Verdict:** key-preserving, as the plan required. No backfill, no migration.

## The gate

Every stored `flight_key` recomputed with the new identity layer and compared
against what is in the table. Read-only; nothing written.

```
rows checked      : 261534
key mismatches    : 0
exit=0
```

This is the whole safety argument for the refactor. A single mismatch would have
meant reverting rather than backfilling — a second identity migration in one week
is not worth a change whose entire value is structural.

## Preconditions re-checked before starting

Both are what make the fold safe:

```
airline values containing a comma                    : 0
timestamps outside YYYY-MM-DDTHH:MM:SS               : 0
```

So moving comma-splitting and timestamp canonicalisation into the identity layer
could not change an existing key by construction, not merely by measurement.

## Suite

```
509 passed, 3 deselected in 37.64s
```

Plus 4 new tests in `tests/test_airline_identity.py` (22 in that file, all
passing): a carrier list keys the same as its first carrier, a seconds-less
timestamp keys the same as the canonical form, an unparseable timestamp still
passes through, and the facet identity equals the stored identity for a table of
names.

## One drift found while consolidating

The two copies of the airline normalisation were **not** byte-identical, which
I had asserted from reading them. `pages._airline_identity` returned a mapped
code uppercased (`"VY"`); `fingerprint._normalize_airline` casefolded it
(`"vy"`). Harmless — each layer was internally consistent, and the facet key is
only ever compared against itself — but it is the drift the consolidation exists
to prevent, already begun, four days after the map was introduced.

Three assertions in `tests/test_filters.py` encoded the uppercase form and were
updated to the casefolded one. Their intent ("the checkbox value is the stable
identity key, not the display name") is untouched; only the expected spelling
moved.

**One-time user-visible consequence:** `filters.js` persists the *unchecked*
airline set in localStorage keyed on the checkbox value. Values change case
once, so any saved selection is ignored on first load after deploy and every
airline comes back checked. It self-heals on the next change, and no data is
affected.
