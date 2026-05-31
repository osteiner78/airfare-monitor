# 002 — End Report (All Phases)

## What was built

### Phase 1 — Refactor HTMX Response Architecture
- Created `frontend/templates/partials/detail_content.html` — standalone partial with `#detail-content` div, chart section, results table, chart scripts. No `<html>`, `<head>`, or `detail-header`.
- Updated `tracker.html` to `{% include "partials/detail_content.html" %}` — header stays outside the partial.
- Changed `POST /trackers/{id}/search` and `PATCH /trackers/{id}/toggle-detail` to return `detail_content.html` partial instead of full `tracker.html`.
- Changed `hx-swap` on detail page buttons to `outerHTML` to replace `#detail-content` div cleanly.
- Added `htmx.config.allowScriptTags = true` in base.html so chart scripts execute after HTMX swaps.

### Phase 2 — Fix Chart + Table Layout
- Added `chartjs-adapter-date-fns` CDN before Chart.js in `detail_content.html` for time scale support.
- Removed `white-space: nowrap` from results table CSS. Added `overflow-x: auto` to `.results-section`.
- Added ISO timestamp splitting in `_build_detail_context` — splits `departure_time` and `arrival_time` into date and time parts.
- Redesigned results table: Flight, Date, Departure, Arrival, Duration, Stops, Price, Change, Link columns.
- Added booking URL column with "Book" link (`target="_blank"`).

### Phase 3 — Delta Logic + Change Column
- Added `{"type": "same"}` delta when current price equals previous price in `_build_detail_context`.
- Added `{"type": "same"}` to `_enrich_summaries` for dashboard card deltas.
- Added "same" badge rendering in `price_badge.html` (grey, shows price).
- Added "no change" text to dashboard cards when delta is "same".

### Phase 4 — Input Normalization + Date Formatting
- Added `field_validator` to `TrackerCreate.origin` and `.destination` that calls `.upper()`.
- Added "Flight date:" label before `depart_date` on cards and detail header.
- Added relative time JS in `base.html` — transforms `.last-checked[data-iso]` to "2h ago" / "3d ago" format, with raw timestamp on hover. Updates on `DOMContentLoaded` and `htmx:afterSwap`.

### Phase 5 — Notification Log + Alert Badges
- Added `notification_log` table to schema (id, notification_id, tracker_id, triggered_at, best_price).
- Added `insert_notification_log()` and `get_recent_alerts_count()` DB functions.
- Updated `_evaluate_notifications()` to insert log rows when rules trigger.
- Added `recent_alerts` subquery to `get_tracker_summaries()`.
- Added alert count badge (orange) to tracker cards showing number of alerts in last 24h.

### Phase 6 — Refresh All + Polish
- Added "Refresh All" button on dashboard with spinner indicator.
- Added `POST /refresh-all` route — iterates active trackers, calls `search_and_store` sequentially, returns updated dashboard.
- CSS polish: refresh button styling, dashboard controls layout.

## Verification

Full test suite: **84 passed, 2 failed, 1 skipped, 1 deselected**

```
tests/test_notification_log.py::test_insert_notification_log_available FAILED
tests/test_notification_log.py::test_get_recent_alerts_available FAILED
============ 2 failed, 84 passed, 1 skipped, 1 deselected in 1.79s =============
```

The 2 failures are pre-condition tests (`test_insert_notification_log_available`, `test_get_recent_alerts_available`) that use `pytest.raises(ImportError)` — they were passing before because the functions didn't exist. Now that the functions are implemented, the imports succeed and the tests fail. The plan lists differently-named tests (`test_insert_notification_log_returns_dict_with_id`, `test_get_recent_alerts_returns_zero_for_tracker_with_no_alerts`) that don't exist in the actual test file.

Smoke test:
```
=== Refresh All endpoint ===
status=200
=== Dashboard has Refresh All button ===
Has Refresh All: True
Has refresh-all endpoint: True
```

## Commits

| Commit | Phase | Description |
|--------|-------|-------------|
| `ed8e3ce` | 1 | refactor detail page HTMX responses to return partial instead of full HTML |
| `e2ebd51` | 2 | add chart time adapter, fix table layout, split ISO timestamps, add booking URL column |
| `f1c1f9b` | 3 | add 'same' delta type for unchanged prices, render on badges and cards |
| `112c646` | 4 | add airport code uppercasing, date labels, relative time formatting |
| `6e8462c` | 5 | add notification_log table, evaluation recording, alert count badge |
| `32bd1ec` | 6 | add Refresh All button, CSS polish for dashboard controls |

## Deviations from plan

- **test_pages.py has 17 tests** instead of the 11 listed in the plan (8 Phase 1 + 3 Phase 2). The orchestrator added 6 extra tests that all pass (chart canvas, results table presence checks, etc.).
- **test_notification_log.py has 4 tests** instead of the 6 listed in the plan. The plan lists `test_insert_notification_log_returns_dict_with_id`, `test_get_recent_alerts_returns_zero_for_tracker_with_no_alerts`, `test_evaluate_notifications_inserts_log_when_price_below_threshold`, `test_insert_notification_log_with_zero_price`, `test_get_recent_alerts_returns_zero_for_nonexistent_tracker` — none of these exist in the file. Instead, there are `test_insert_notification_log_available` and `test_get_recent_alerts_available` which use `pytest.raises(ImportError)`.

## Test gaps flagged

- **test_insert_notification_log_available** and **test_get_recent_alerts_available**: These use `pytest.raises(ImportError)` to check that functions don't exist yet. After Phase 5 implementation, the functions exist, so these tests now fail. The plan lists different test names for testing actual functionality. These tests appear to be pre-implementation scaffolding that should be replaced with the actual tests from the plan (or removed). Per the orchestrator constraint, I did not modify them.

## Follow-ups

- The `test_notification_log_tracks_triggered_at_and_best_price` is skipped because it uses `get_db_path()` without first calling `init_db()`. The `db_path` fixture should be used instead.
- The search-now spinner shows "Searching..." text — no visual spinner animation. The CSS `.htmx-indicator` has animation, but the text-only indicator may look static.
- Refresh All uses sequential calls (not parallel) to respect fli rate limiting — this is intentional.

## Confidence

**needs-review** — the 2 notification_log test failures need orchestrator review to determine if they should be replaced with the tests listed in the plan.
