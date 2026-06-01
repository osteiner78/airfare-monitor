# 006 — Logging System + Monitoring Dashboard

## What this builds

A structured logging system (DB-backed) and a monitoring dashboard at `/monitor`. Currently exceptions are silently swallowed (`scheduler.py:30-31` has bare `except Exception: pass`), and there's no way to check system health without reading raw server output.

---

## Phase 1 — Logging Infrastructure

### Tasks

| # | Task | Files |
|---|------|-------|
| 1.1 | Add `system_logs` table to DB schema: `id`, `level` (INFO/WARNING/ERROR), `event` (search_start/search_done/search_error/tracker_created/tracker_paused/tracker_resumed/tracker_deleted/notification_triggered), `tracker_id` (nullable), `message`, `created_at` | `backend/db.py` |
| 1.2 | Add `insert_log()` DB function | `backend/db.py` |
| 1.3 | Add `get_recent_logs(limit=50)` DB function | `backend/db.py` |
| 1.4 | Wire logging into `scheduler.py`: log search_start/search_done (with result count)/search_error (with exception message). Log notification_triggered | `backend/scheduler.py` |
| 1.5 | Wire logging into `pages.py`: log tracker_created (add form + API), tracker_paused, tracker_resumed, tracker_deleted | `backend/pages.py`, `backend/api.py` |

### Key design decisions

- `level` uses Python logging level names (INFO, WARNING, ERROR) for consistency.
- `event` is a snake_case string identifier — queryable for filtering.
- `tracker_id` is nullable — some events (server startup) don't relate to a tracker.
- `create_tracker` in `db.py` is called from BOTH `pages.py` (form) and `api.py` (JSON). Logging at the call site (not inside create_tracker) lets us distinguish form vs API creation.
- All `insert_log()` calls use `await` — async DB write.

### What NOT to touch

- `backend/models.py`
- `frontend/` templates (Phase 2)
- `test_*` files (Phase 3)

### Verification

```bash
# DB schema check
python -c "
import asyncio, aiosqlite, os
os.environ['AIRFARE_DB_PATH'] = 'data/airfare.db'
async def check():
    async with aiosqlite.connect('data/airfare.db') as db:
        async with db.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"system_logs\"') as c:
            print('table exists:', await c.fetchone() is not None)
asyncio.run(check())
"

pytest tests/ -v -k "not slow"
# all 90 existing tests must pass
```

---

## Phase 2 — Monitoring Dashboard

### Tasks

| # | Task | Files |
|---|------|-------|
| 2.1 | Add `GET /monitor` route to `pages.py` — queries recent logs, tracker stats, DB stats | `backend/pages.py` |
| 2.2 | Create `frontend/templates/monitor.html` — full HTML page with log table, tracker summaries, DB stats | `frontend/templates/monitor.html` |
| 2.3 | Add HTMX polling to auto-refresh logs every 30 seconds (`hx-get="/monitor/logs" hx-trigger="every 30s"`) | `frontend/templates/monitor.html` |
| 2.4 | Add `GET /monitor/logs` partial route returning only the log table rows (HTMX swap target) | `backend/pages.py` |
| 2.5 | Add `get_tracker_stats()` DB function — returns active count, paused count, total count | `backend/db.py` |
| 2.6 | Add `get_db_stats()` DB function — returns snapshot count, price count, DB file path | `backend/db.py` |
| 2.7 | Add "Monitor" link to dashboard and detail page (small link in header or footer) | `frontend/templates/dashboard.html`, `frontend/templates/tracker.html` |
| 2.8 | CSS for monitor page: styled log rows (color-coded by level), stat cards, auto-refresh indicator | `frontend/static/app.css` |

### Key design decisions

- Auto-refresh uses HTMX polling (`hx-trigger="every 30s"`) on the logs table partial. Stat cards are static (loaded once).
- Monitoring page layout: stat cards row at top, log table below.
- Log rows color-coded: ERROR = red bg, WARNING = yellow bg, INFO = no highlight.
- DB stats: count snapshots, flight_prices rows, and include the DB file path.
- The `/monitor` page extends `base.html` — consistent shell with error banner.

### Monitor page layout

```
[Airfare Monitor]                    [Dashboard link]

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ 5 Active     │ 2 Paused     │ 1,234 Prices │ 45 Snapshots │
└──────────────┴──────────────┴──────────────┴──────────────┘

System Logs (auto-refresh every 30s)
┌────────────────────────────────────────────────────────────┐
│ ERROR  search_error  Tracker #2  Rate limited (429)  2m ago│
│ INFO   search_done   Tracker #1  151 results          5m ago│
│ INFO   tracker_created           GVA → BCN            1h ago│
│ ...                                                        │
└────────────────────────────────────────────────────────────┘
```

### What NOT to touch

- `backend/scheduler.py` (wire in Phase 1)
- `backend/api.py` (wire in Phase 1)

### Verification

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/monitor
# expect: 200

curl -s http://localhost:8000/monitor | grep -c "system_logs"
# expect: >0

pytest tests/ -v -k "not slow"
# all existing 90 tests pass
```

---

## Phase 3 — Tests + Integration

### Tasks

| # | Task | Files |
|---|------|-------|
| 3.1 | Write `tests/test_logging.py` — verify `insert_log()` returns dict with id, `get_recent_logs()` returns logs in descending order, event types filter correctly | `tests/test_logging.py` |
| 3.2 | Verify monitor page returns 200 via test | `tests/test_logging.py` |
| 3.3 | Verify log entries are created when a tracker is created/deleted via API | `tests/test_logging.py` |
| 3.4 | Full regression pass | Tests |

### Tests

New file: `tests/test_logging.py`

| Label | Test name | Status |
|-------|-----------|--------|
| NEW-BEHAVIOR | `test_insert_log_returns_dict_with_id` | Fails — function not yet implemented |
| NEW-BEHAVIOR | `test_get_recent_logs_returns_newest_first` | Fails |
| NEW-BEHAVIOR | `test_get_recent_logs_respects_limit` | Fails |
| NEW-BEHAVIOR | `test_monitor_page_returns_200` | Fails |
| NEW-BEHAVIOR | `test_tracker_creation_creates_log_entry` | Fails |
| FAILURE-MODE | `test_insert_log_with_null_tracker_id` | Fails |

### Verification

```bash
pytest tests/test_logging.py -v
# all 6 MUST FAIL before implementation

pytest tests/ -v -k "not slow"
# all 96 tests pass after Phase 3
```

---

## Test Files Summary

| File | Tests | Phase |
|------|-------|-------|
| `tests/test_logging.py` | 6 | Phase 3 |

---

## Handoff Notes

### Key files

| File | Purpose |
|------|---------|
| `backend/db.py` | New: `system_logs` table, `insert_log()`, `get_recent_logs()`, `get_tracker_stats()`, `get_db_stats()` |
| `backend/scheduler.py` | Add `insert_log()` calls at each event |
| `backend/pages.py` | Add `insert_log()` calls in tracker lifecycle routes; new `/monitor` and `/monitor/logs` routes |
| `backend/api.py` | Add `insert_log()` calls in tracker lifecycle endpoints |
| `frontend/templates/monitor.html` | New: monitoring dashboard page |
| `frontend/static/app.css` | New: monitor page styles |
| `frontend/templates/dashboard.html` | Add monitor link |
| `frontend/templates/tracker.html` | Add monitor link |
| `tests/test_logging.py` | New: logging + monitor page tests |

### Constraints

- All `insert_log()` calls are async — `await insert_log(...)`
- DB path always from `os.environ["AIRFARE_DB_PATH"]`
- `import backend.scheduler` module-reference pattern
- Log table has no foreign key constraints (tracker_id can be NULL for non-tracker events like server errors)
- Auto-refresh uses HTMX `hx-trigger="every 30s"` with `hx-get="/monitor/logs"` targeting the tbody
