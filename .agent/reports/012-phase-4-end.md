# Plan 012 — Phase 4 report

## What was built

### 4.1 Monitor link affordance
`.monitor-link` now renders as a secondary button: same `padding`, `border`, `border-radius: 4px`, and `background: #f0f0f0` as `.refresh-all-btn`. Hover removes the blue text and shows a subtle grey darken instead. The two adjacent controls now read as peers.

### 4.2 Primary CTA palette — `--accent` token
Added `--accent: #4a90d9` and `--accent-dark: #3a7bc8` to `:root`. Replaced every hardcoded occurrence of those hex values throughout `app.css` (focus borders, button backgrounds, spinner ring, back-link, gf-link, search-now-btn, airline-action-link). Only the token definition lines retain the literals.

### 4.3 Native date input
Added `.form-row input[type="date"] { -webkit-appearance: none; appearance: none; }` so the browser's default date-picker chrome is suppressed and the input inherits the existing `.form-row input` border/padding/radius uniformly.

## Verification output

```
$ .venv/bin/python -m pytest tests/ -q -k "not slow"
182 passed, 1 deselected in 3.17s
```

Remaining hardcoded accent colors after change:
```
$ grep "#4a90d9\|#3a7bc8" frontend/static/app.css
19:    --accent: #4a90d9;
20:    --accent-dark: #3a7bc8;
```
Only the token definitions — no stray occurrences.

## Commit hash

- `22fca5c` — `[phase-4]` page-chrome polish

## Deviations from plan

None. All three tasks implemented as specified.

## Follow-ups

- The `rgba(74, 144, 217, 0.2)` focus ring shadow at line ~117 retains a literal RGB value because CSS custom properties cannot be used inside `rgba()` without color-mix or level-5 color syntax. This is the only remaining hard reference to the accent color value and is acceptable until broader browser support for `color-mix()` arrives.

## Confidence rating

**certain** — 182 tests green, no stray hardcoded accent colors outside the token definition.
