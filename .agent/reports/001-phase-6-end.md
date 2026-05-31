# 001 Phase 6 — End Report

## What was built

- **Task 6.4**: Added `NotificationCreate` and `NotificationResponse` models to `backend/models.py`. Three notification API routes in `backend/api.py`: `POST /api/notifications` (201), `GET /api/trackers/{id}/notifications` (200), `DELETE /api/notifications/{id}` (204/404). Added `get_notification()` to `backend/db.py` for existence checking before delete.
- **Task 6.5**: Added `_evaluate_notifications()` to `backend/scheduler.py`. Called after each search stores prices — checks notification rules (price_below, price_above) against the current best price. Evaluation function is ready for v2 delivery transport.
- **Task 6.6**: CSS spinner for `.htmx-indicator` — animated rotating border with `@keyframes spinner`. Visible during HTMX requests via `.htmx-request .htmx-indicator`.
- **Task 6.7**: Global error banner (`#error-banner`) in `base.html` with `htmx:responseError` listener. Auto-hides after 5 seconds. Styled with red background.
- **Task 6.8**: Responsive layout via `@media (max-width: 600px)` — stacks form fields, card headers, and detail controls vertically. Adds horizontal scroll to results table.

## Verification output

Full test suite: **54 passed, 1 deselected** (slow/live).

```
tests/test_notifications.py::test_notifications_table_exists_after_init PASSED
tests/test_notifications.py::test_create_notification_returns_dict_with_id PASSED
tests/test_notifications.py::test_list_notifications_returns_empty_for_tracker_with_no_rules PASSED
tests/test_notifications.py::test_delete_notification_removes_the_row PASSED
tests/test_notifications.py::test_post_notification_api_returns_201_with_id PASSED
tests/test_notifications.py::test_get_notifications_api_returns_empty_list_for_new_tracker PASSED
tests/test_notifications.py::test_delete_notification_api_returns_404_for_unknown_id PASSED
tests/test_notifications.py::test_post_notification_api_returns_404_for_unknown_tracker_id PASSED

54 passed, 1 deselected in 1.04s
```

Smoke test:

```
=== Dashboard loads ===
status=200
=== Create tracker ===
Tracker id: 1
=== Detail page ===
status=200
=== Notifications API ===
  Create: status=201
  List: status=200
  Delete: status=204
  Delete unknown (expect 404): status=404
=== Error banner present ===
Has error banner: True
Has htmx:responseError listener: True
=== CSS file check ===
Has spinner keyframes: True
Has media query: True
Has error-banner: True
Has cursor:pointer: True
```

## Deviations from plan

- **Added `get_notification()` to db.py**: Needed for the delete endpoint to return 404 for non-existent notifications, as the test expects. Minimal addition.

## Test gaps

None. All 8 orchestrator-written notification tests pass.

## Follow-ups

- Notification delivery transport (email, push) is not implemented — this is explicitly v2. The evaluation function and DB table are ready.
- The `_evaluate_notifications` function only checks the best price against thresholds. In v2 it could check individual flight prices.
- The error banner only handles HTMX errors — non-HTMX errors (like initial page load failures) are not covered. Acceptable for v1.

## Confidence

**certain** — all 54 tests pass, smoke test confirms all endpoints and UI elements.
