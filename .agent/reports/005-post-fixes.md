# 005 Post-Implementation Fixes

## Issues fixed after initial chart deployment

| # | Problem | Root cause | Fix | Commit |
|---|---------|-----------|-----|--------|
| 1 | Chart blank | `chartjs-adapter-date-fns` CDN fails silently on some browsers. The adapter resolves (HTTP 200) but the browser may block it due to CORS/Content-Type mismatch. | Switched to numeric axis (`type: "linear"`) with `new Date(iso).getTime()` for x-values and custom `ticks.callback` formatting. Removed adapter CDN from `detail_page.html`. Documented in CLAUDE.md. | `c6a9685`, `86337d5` |
| 2 | Chart shows 20-30 lines instead of 5 | Sticky top-N (union across all snapshots) accumulates flight keys over time. DB default was `top_n=10` in existing databases (schema `IF NOT EXISTS` doesn't update). | Changed to show only the latest snapshot's top N cheapest flights. Updated schema default to 5. Pass `top_n=5` explicitly in form POST. Updated CLAUDE.md. | `59cf43a`, `41801b8` |
| 3 | Chart labels too long | Labels included full airline names (e.g., "ITA AZ 675+AZ 2036+AZ 312"). | Labels now use `flight_number` DB field only, which contains IATA codes + numbers (e.g., "AZ 675+AZ 2036+AZ 312"). | `15274f0` |

## Current chart behavior

- Shows exactly 5 cheapest flights from the latest snapshot
- Numeric x-axis with custom date/time tick formatting
- Legend below chart (click to toggle lines)
- No animation (clean HTMX swaps)
- Labels: IATA codes + flight numbers only

## Verification

94 tests pass, 1 deselected (slow/live).

```
94 passed, 1 deselected in 1.21s
```
