# 001 — Airfare Tracker v1

## What this builds

Flight prices for a given route are not fixed — they fluctuate daily, sometimes wildly, in the weeks before departure. If you know you want to fly GVA→BCN on a specific date, the question is never "how much does it cost?" but "is this a good price right now, and should I buy or wait?"

This tool answers that question. You register a route and travel date ("I want to fly GVA→BCN on 15 Sep 2026"), and the system searches for flights every few hours, records what it finds, and builds a price-history chart over time. When you check back tomorrow or next week, you can see whether prices are trending up, down, or holding steady — and make a buy/wait decision with actual data rather than gut feel.

**The user experience in one paragraph:** Open the dashboard, click "Add Route," fill in origin, destination, and date. A card appears showing the current best price. Every three hours the system re-searches in the background and updates the chart. Click the card to see a detail page: a line chart showing every tracked flight's price over time (so you can spot which flights swing most), a table of today's results with colour-coded arrows showing whether each flight got cheaper or more expensive since last check, and a "Search Now" button if you want a fresh snapshot immediately. You can pause tracking for a route (stops background searches, keeps the history), resume it, or delete it entirely.

**What it is not:** a booking engine, a price-alert push-notifier (that's v2), or a tool that covers every airline. It's a personal price journal — lightweight, local, zero ongoing cost.

---

## Architecture

```
airfare-monitor/
├── backend/
│   ├── main.py              # FastAPI app, static mount, lifecycle
│   ├── db.py                # aiosqlite, schema, all query functions
│   ├── models.py            # Pydantic schemas (request/response)
│   ├── api.py               # REST router: /api/trackers/*
│   ├── pages.py             # HTML page router: / and /trackers/{id}
│   ├── scheduler.py         # AsyncIOScheduler — per-tracker periodic search
│   ├── fingerprint.py       # flight_key generation from FlightResult
│   └── sources/
│       ├── __init__.py
│       ├── base.py          # FlightResult dataclass, SearchSource protocol
│       └── google_flights.py
├── frontend/
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── tracker.html
│   │   └── partials/
│   │       ├── tracker_card.html
│   │       ├── add_form.html
│   │       ├── results_table.html
│   │       └── price_badge.html
│   └── static/
│       ├── app.css
│       └── charts.js
├── tests/
│   ├── conftest.py          # shared fixtures: db_path, db_conn, client
│   ├── test_db.py           # Phase 1
│   ├── test_fingerprint.py  # Phase 2
│   ├── test_sources.py      # Phase 2
│   ├── test_api.py          # Phase 3
│   └── test_notifications.py # Phase 6
├── data/                    # SQLite DB auto-created at runtime
├── requirements.txt
└── pyproject.toml           # pytest-asyncio config lives here
```

## Database Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE trackers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    return_date TEXT,
    currency TEXT NOT NULL DEFAULT 'EUR',
    interval_minutes INTEGER NOT NULL DEFAULT 180,
    top_n INTEGER NOT NULL DEFAULT 10,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    searched_at TEXT NOT NULL DEFAULT (datetime('now')),
    results_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE flight_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    flight_key TEXT NOT NULL,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    duration_min INTEGER,
    stops INTEGER,
    airline TEXT,
    flight_number TEXT,
    departure_time TEXT,
    arrival_time TEXT,
    legs_json TEXT,
    booking_url TEXT
);

CREATE INDEX idx_prices_tracker_key ON flight_prices(tracker_id, flight_key);
CREATE INDEX idx_snapshots_tracker ON snapshots(tracker_id, searched_at);
```

### flight_key format

`{source}|{airline_codes}|{flight_numbers}|{first_leg_dep_iso}`

| Example | Type |
|---------|------|
| `google_flights\|LX\|LX1234\|2026-06-15T07:30:00+02:00` | Nonstop |
| `google_flights\|LH+OS\|LH1234+OS5678\|2026-06-15T07:30:00+02:00` | 1 stop |

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Dashboard HTML page |
| `GET` | `/trackers/{id}` | Tracker detail HTML page |
| `POST` | `/api/trackers` | Create tracker → immediate search |
| `GET` | `/api/trackers` | List all with best price + Δ |
| `GET` | `/api/trackers/{id}` | Single tracker |
| `PATCH` | `/api/trackers/{id}` | Toggle active, change interval |
| `DELETE` | `/api/trackers/{id}` | Delete + cascade |
| `POST` | `/api/trackers/{id}/search` | Trigger manual search |
| `GET` | `/api/trackers/{id}/history` | Price time-series for chart |

### Source abstraction

```python
class FlightResult:
    source: str
    price: float
    currency: str
    duration_min: int | None
    stops: int
    airline: str
    flight_number: str
    departure_time: str   # ISO 8601
    arrival_time: str
    legs_json: str
    booking_url: str

class SearchSource(Protocol):
    async def search(self, origin, dest, depart_date, return_date, currency, top_n) -> list[FlightResult]
```

### Price change detection

| Condition | UI Badge |
|-----------|----------|
| Price dropped | Green `↓ -€X` |
| Price increased | Red `↑ +€X` |
| Same | None |
| New flight | Blue `new` |
| Missing 1x | Yellow `?` |
| Missing 2x consecutively | Remove from chart |

### Edge cases

| Case | Behavior |
|------|----------|
| fli not installed | Source returns `[]`, snapshot records 0 results |
| Rate limited (429) | Exception caught, logged, skip cycle |
| All sources fail | Snapshot with 0 results, chart gap, scheduler continues |
| Far-future dates | fli returns empty until inventory opens |
| Flight disappears 2x | Exclude from history response |
| DB contention | WAL mode — concurrent reads + serialized writes |
| Server restart | Rebuild all active tracker jobs, fire immediate search |

### DB path convention

All db functions read the database path from `os.environ["AIRFARE_DB_PATH"]` with fallback `"data/airfare.db"`. `init_db(path=None)` accepts an explicit override. Tests set `AIRFARE_DB_PATH` via monkeypatch before calling any db function.

---

## Phase 1 — Scaffold + Database

Vertical slice: database exists, schema is validated, CRUD operations work from Python.

### Tasks

| # | Task | Files |
|---|------|-------|
| 1.1 | Create project directory tree | `backend/sources/`, `frontend/templates/partials/`, `frontend/static/`, `data/`, `tests/` |
| 1.2 | Write `pyproject.toml` | `pyproject.toml` |
| 1.3 | Write `requirements.txt` | `requirements.txt` |
| 1.4 | Verify pre-written fixtures fail correctly (orchestrator-written) | `tests/conftest.py`, `tests/__init__.py` |
| 1.5 | Verify pre-written Phase 1 tests fail correctly (orchestrator-written) | `tests/test_db.py` |
| 1.6 | Implement `db.py` — schema DDL + init | `backend/db.py` |
| 1.7 | Implement `db.py` — tracker CRUD | `backend/db.py` |
| 1.8 | Implement `db.py` — snapshot + prices | `backend/db.py` |
| 1.9 | Implement `db.py` — history + summaries | `backend/db.py` |
| 1.10 | Add `data/.gitkeep` | `data/.gitkeep` |

### Tests

Test file: `tests/test_db.py`

| Label | Test name |
|-------|-----------|
| NEW-BEHAVIOR | `test_wal_mode_enabled_after_init` |
| NEW-BEHAVIOR | `test_trackers_table_exists_after_init` |
| NEW-BEHAVIOR | `test_snapshots_table_exists_after_init` |
| NEW-BEHAVIOR | `test_flight_prices_table_exists_after_init` |
| NEW-BEHAVIOR | `test_create_tracker_returns_dict_with_id` |
| NEW-BEHAVIOR | `test_create_tracker_stores_all_provided_fields` |
| NEW-BEHAVIOR | `test_list_trackers_returns_empty_list_when_no_trackers_exist` |
| NEW-BEHAVIOR | `test_get_tracker_returns_tracker_by_id` |
| NEW-BEHAVIOR | `test_update_tracker_sets_active_to_false` |
| NEW-BEHAVIOR | `test_delete_tracker_removes_the_row` |
| NEW-BEHAVIOR | `test_delete_tracker_cascades_to_snapshots` |
| NEW-BEHAVIOR | `test_create_snapshot_returns_dict_with_id` |
| NEW-BEHAVIOR | `test_get_price_history_returns_empty_for_tracker_with_no_snapshots` |
| NEW-BEHAVIOR | `test_get_tracker_summaries_returns_empty_list_when_no_trackers` |
| FAILURE-MODE | `test_get_tracker_returns_none_when_id_does_not_exist` |
| FAILURE-MODE | `test_get_tracker_returns_none_for_zero_id` |
| FAILURE-MODE | `test_get_tracker_returns_none_for_negative_id` |
| FAILURE-MODE | `test_delete_tracker_on_missing_id_does_not_raise` |

### Success criteria

All tests in `tests/test_db.py` pass. Full output pasted into `.agent/reports/001-phase-1.md`.

### Verification

```bash
# confirm tests fail before implementation (all ImportError — expected for greenfield)
pytest tests/test_db.py -v 2>&1 | head -40

# after implementation: all must pass
pytest tests/test_db.py -v 2>&1 | tee .agent/reports/001-phase-1.md

# schema spot-check
python -c "
import aiosqlite, asyncio
async def check():
    async with aiosqlite.connect('data/test.db') as db:
        async with db.execute(\"PRAGMA journal_mode\") as c: print('journal:', (await c.fetchone())[0])
        async with db.execute(\"PRAGMA table_info(trackers)\") as c: print('trackers cols:', [r[1] for r in await c.fetchall()])
asyncio.run(check())
"
```

### Risks

- aiosqlite vs sqlite3: aiosqlite adds a dependency but simplifies async access. Acceptable.
- Schema changes after v1 require migrations. Keep schema minimal.

---

## Phase 2 — Flight Search Engine

Vertical slice: Google Flights search returns structured `FlightResult` objects with correct fingerprinting.

### Tasks

| # | Task | Files |
|---|------|-------|
| 2.1 | Verify pre-written Phase 2 tests fail correctly (orchestrator-written) | `tests/test_fingerprint.py`, `tests/test_sources.py` |
| 2.2 | Implement `FlightResult` dataclass | `backend/sources/base.py` |
| 2.3 | Implement `SearchSource` protocol | `backend/sources/base.py` |
| 2.4 | Implement Google Flights source | `backend/sources/google_flights.py` |
| 2.5 | Handle fli import error gracefully | `backend/sources/google_flights.py` |
| 2.6 | Handle search exceptions | `backend/sources/google_flights.py` |
| 2.7 | Implement `fingerprint.py` | `backend/fingerprint.py` |
| 2.8 | Create `sources/__init__.py` | `backend/sources/__init__.py` |

### Tests

Test files: `tests/test_fingerprint.py`, `tests/test_sources.py`

| Label | Test name | File |
|-------|-----------|------|
| NEW-BEHAVIOR | `test_nonstop_key_contains_four_pipe_separated_parts` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_nonstop_key_starts_with_source_name` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_nonstop_key_contains_airline_and_flight_number` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_multistop_key_joins_airlines_with_plus` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_multistop_key_joins_flight_numbers_with_plus` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_same_flight_result_produces_same_key_on_repeated_calls` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_different_departure_times_produce_different_keys` | `test_fingerprint.py` |
| NEW-BEHAVIOR | `test_flight_result_dataclass_has_all_required_fields` | `test_sources.py` |
| NEW-BEHAVIOR | `test_all_sources_returns_nonempty_list` | `test_sources.py` |
| NEW-BEHAVIOR | `test_google_flights_source_satisfies_search_source_protocol` | `test_sources.py` |
| FAILURE-MODE | `test_key_with_empty_airline_still_produces_four_parts` | `test_fingerprint.py` |
| FAILURE-MODE | `test_google_flights_returns_empty_list_when_fli_raises_import_error` | `test_sources.py` |
| FAILURE-MODE | `test_google_flights_returns_empty_list_when_search_raises_exception` | `test_sources.py` |

### Success criteria

All tests in `tests/test_fingerprint.py` and `tests/test_sources.py` pass. `test_google_flights_source_satisfies_search_source_protocol` passes with a live network call (marked `slow`). Full output pasted into `.agent/reports/001-phase-2.md`.

### Verification

```bash
# unit tests (no network)
pytest tests/test_fingerprint.py tests/test_sources.py -v -k "not slow" 2>&1 | tee .agent/reports/001-phase-2.md

# live search (requires network + fli installed)
pytest tests/test_sources.py -v -m slow

# full suite regression check
pytest tests/test_db.py tests/test_fingerprint.py tests/test_sources.py -v
```

### Risks

- fli is synchronous — must be called via `asyncio.to_thread()` to avoid blocking the event loop.
- fli is a community library; Google page changes can break it. Isolation in `google_flights.py` means swapping sources is a single-file change.
- Rate limiting: Google may throttle repeated queries. 3-hour default interval should be safe.

---

## Phase 3 — API + Scheduler

Vertical slice: FastAPI server runs, trackers can be created via HTTP, APScheduler stores results periodically.

### Tasks

| # | Task | Files |
|---|------|-------|
| 3.1 | Verify pre-written Phase 3 tests fail correctly (orchestrator-written) | `tests/test_api.py` |
| 3.2 | Implement `models.py` | `backend/models.py` |
| 3.3 | Implement scheduler module | `backend/scheduler.py` |
| 3.4 | Implement `search_and_store` | `backend/scheduler.py` |
| 3.5 | Implement API router — CRUD | `backend/api.py` |
| 3.6 | Implement API router — search + history | `backend/api.py` |
| 3.7 | Integrate scheduler into CRUD | `backend/api.py` |
| 3.8 | Implement `main.py` | `backend/main.py` |
| 3.9 | Startup: rebuild jobs | `backend/main.py` |

### Tests

Test file: `tests/test_api.py`

Note: `search_and_store` is mocked to `AsyncMock()` in the `client` fixture — tests verify API behaviour only, not flight data fetching.

| Label | Test name |
|-------|-----------|
| NEW-BEHAVIOR | `test_get_trackers_returns_empty_list_initially` |
| NEW-BEHAVIOR | `test_post_trackers_returns_201_with_tracker_id` |
| NEW-BEHAVIOR | `test_post_trackers_adds_tracker_visible_in_list` |
| NEW-BEHAVIOR | `test_get_tracker_by_id_returns_tracker` |
| NEW-BEHAVIOR | `test_patch_tracker_sets_active_to_false` |
| NEW-BEHAVIOR | `test_delete_tracker_returns_204` |
| NEW-BEHAVIOR | `test_delete_tracker_removes_tracker_from_list` |
| NEW-BEHAVIOR | `test_get_history_returns_empty_flights_for_new_tracker` |
| NEW-BEHAVIOR | `test_post_search_returns_200` |
| FAILURE-MODE | `test_get_tracker_returns_404_for_unknown_id` |
| FAILURE-MODE | `test_delete_tracker_returns_404_for_unknown_id` |
| FAILURE-MODE | `test_post_trackers_returns_422_when_origin_is_missing` |
| FAILURE-MODE | `test_post_trackers_returns_422_when_destination_is_missing` |
| FAILURE-MODE | `test_post_trackers_returns_422_when_depart_date_is_missing` |
| FAILURE-MODE | `test_post_trackers_returns_422_when_depart_date_format_is_invalid` |

### Success criteria

All tests in `tests/test_api.py` pass. Full output pasted into `.agent/reports/001-phase-3.md`.

### Verification

```bash
pytest tests/test_api.py -v 2>&1 | tee .agent/reports/001-phase-3.md

# smoke test against live server
uvicorn backend.main:app &
sleep 2
curl -s http://localhost:8000/api/trackers | python -c "import sys,json; data=json.load(sys.stdin); print('API ok, trackers:', len(data))"
kill %1 2>/dev/null

# full suite regression
pytest tests/ -v -k "not slow"
```

### Risks

- AsyncIOScheduler + FastAPI lifecycle: scheduler must start after DB init and stop before shutdown. Use FastAPI `lifespan` handler.
- fli is sync: `search_and_store` must call it via `asyncio.to_thread()`.
- `next_run_time` for immediate search: set to `datetime.now()` when adding a job.

---

## Phase 4 — Frontend Dashboard

Vertical slice: browser shows dashboard with all trackers, inline add form works, pause/resume/delete from dashboard.

### Tasks

| # | Task | Files |
|---|------|-------|
| 4.1 | Implement `pages.py` | `backend/pages.py` |
| 4.2 | Create `base.html` shell | `frontend/templates/base.html` |
| 4.3 | Create `app.css` | `frontend/static/app.css` |
| 4.4 | Create `dashboard.html` | `frontend/templates/dashboard.html` |
| 4.5 | Create `add_form.html` partial | `frontend/templates/partials/add_form.html` |
| 4.6 | Create `tracker_card.html` partial | `frontend/templates/partials/tracker_card.html` |
| 4.7 | Wire HTMX: add tracker | `frontend/templates/dashboard.html` |
| 4.8 | Wire HTMX: pause/resume/delete | `frontend/templates/dashboard.html` |

### Tests

No unit tests for Phase 4. Behaviour is verified by manual smoke test and the HTTP checks below.

### Success criteria

- `GET /` returns 200 with HTML containing "No trackers yet" when empty.
- Submitting the add form → card appears without page reload.
- Card shows route, date, best price, Δ, "Active" badge, last checked time.
- Pause button → card shows "Paused" badge; scheduler stops.
- Delete with confirmation → card removed; DB cascade deletes data.
- Refreshing the page persists all state.

### Verification

```bash
uvicorn backend.main:app --reload &
sleep 2

# page loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
# expect: 200

# POST via form-encoding (HTMX simulation)
curl -s -X POST http://localhost:8000/api/trackers \
  -H "Content-Type: application/json" \
  -d '{"origin":"GVA","destination":"BCN","depart_date":"2026-09-15"}' \
  | python -c "import sys,json; t=json.load(sys.stdin); print('created id:', t['id'])"

kill %1 2>/dev/null
# Then: open http://localhost:8000 and manually verify card appears, pause/delete work
```

### Risks

- HTMX swallows 4xx/5xx silently by default — add `hx-on::after-request` for error feedback.
- Jinja2 autoescape: use `|e` for user-supplied strings; `|safe` only for trusted server values.
- "Last checked" time: format client-side with a small JS snippet from ISO 8601.

---

## Phase 5 — Tracker Detail + Chart

Vertical slice: click a tracker card → detail page with Chart.js price history chart, results table with Δ badges, search-now button.

### Tasks

| # | Task | Files |
|---|------|-------|
| 5.1 | Create `tracker.html` | `frontend/templates/tracker.html` |
| 5.2 | Create `charts.js` | `frontend/static/charts.js` |
| 5.3 | Create `results_table.html` partial | `frontend/templates/partials/results_table.html` |
| 5.4 | Create `price_badge.html` partial | `frontend/templates/partials/price_badge.html` |
| 5.5 | Wire HTMX: search now | `frontend/templates/tracker.html` |
| 5.6 | Wire HTMX: pause/resume/delete | `frontend/templates/tracker.html` |

### Tests

No unit tests for Phase 5. Behaviour is verified by the HTTP checks and manual smoke test below.

### Success criteria

- `GET /trackers/1` returns 200 with HTML after a tracker is created.
- Chart renders: X-axis = time, Y-axis = price, one line per tracked flight.
- Results table shows flights sorted by price with correct Δ badges.
- "Search Now" button updates results table and chart without page reload.
- Pause/resume works from detail page.
- Delete redirects to dashboard.
- Empty tracker shows appropriate empty state.

### Verification

```bash
uvicorn backend.main:app --reload &
sleep 2

# create a tracker
ID=$(curl -s -X POST http://localhost:8000/api/trackers \
  -H "Content-Type: application/json" \
  -d '{"origin":"GVA","destination":"BCN","depart_date":"2026-09-15"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['id'])")

# detail page loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/trackers/$ID
# expect: 200

# history endpoint
curl -s http://localhost:8000/api/trackers/$ID/history \
  | python -c "import sys,json; h=json.load(sys.stdin); print('flights:', len(h['flights']), 'best_prices:', len(h['best_prices']))"

kill %1 2>/dev/null
# Then: manually verify chart, badges, Search Now, delete
```

### Risks

- Chart.js CDN: acceptable for v1; bundle locally if offline use is needed.
- Large datasets (100+ points): keep history query to last 90 days of snapshots.
- Chart resize: use `responsive: true` + `maintainAspectRatio: false` in a relative-sized container.
- After "Search Now": re-fetch history and call `chart.data = newData; chart.update()`.

---

## Phase 6 — Notification Foundation + Polish

Vertical slice: notification data model exists (future-ready), edge cases handled in UI, loading/error states present.

### Tasks

| # | Task | Files |
|---|------|-------|
| 6.1 | Verify pre-written Phase 6 tests fail correctly (orchestrator-written) | `tests/test_notifications.py` |
| 6.2 | Add notifications table to schema | `backend/db.py` |
| 6.3 | Add notification CRUD to db | `backend/db.py` |
| 6.4 | Add notification API endpoints | `backend/api.py` |
| 6.5 | Implement notification evaluation | `backend/scheduler.py` |
| 6.6 | Add HTMX loading indicators | `frontend/templates/base.html` |
| 6.7 | Add error state handling | `frontend/templates/` |
| 6.8 | Responsive layout pass | `frontend/static/app.css` |
| 6.9 | Final end-to-end smoke test | — |

### Tests

Test file: `tests/test_notifications.py`

| Label | Test name |
|-------|-----------|
| NEW-BEHAVIOR | `test_notifications_table_exists_after_init` |
| NEW-BEHAVIOR | `test_create_notification_returns_dict_with_id` |
| NEW-BEHAVIOR | `test_list_notifications_returns_empty_for_tracker_with_no_rules` |
| NEW-BEHAVIOR | `test_delete_notification_removes_the_row` |
| NEW-BEHAVIOR | `test_post_notification_api_returns_201_with_id` |
| NEW-BEHAVIOR | `test_get_notifications_api_returns_empty_list_for_new_tracker` |
| FAILURE-MODE | `test_delete_notification_api_returns_404_for_unknown_id` |
| FAILURE-MODE | `test_post_notification_api_returns_404_for_unknown_tracker_id` |

### Success criteria

All tests in `tests/test_notifications.py` pass. Full suite `pytest tests/ -k "not slow"` passes. Full output pasted into `.agent/reports/001-phase-6.md`.

### Verification

```bash
pytest tests/test_notifications.py -v 2>&1 | tee .agent/reports/001-phase-6.md

# full suite
pytest tests/ -v -k "not slow" 2>&1 | tee -a .agent/reports/001-phase-6.md

# DB schema check — notifications table
python -c "
import aiosqlite, asyncio
async def check():
    async with aiosqlite.connect('data/airfare.db') as db:
        async with db.execute(\"PRAGMA table_info(notifications)\") as c:
            print('notifications cols:', [r[1] for r in await c.fetchall()])
asyncio.run(check())
"
```

### Risks

- Notification delivery (email, push) is deliberately NOT implemented in v1. Table + API + evaluation logic only.
- HTMX indicator CSS: test `.htmx-request` spinner on each interactive element individually.

---

## Handoff Notes

### Key files to start with

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures — read before writing any implementation |
| `backend/db.py` | Start here — everything depends on it |
| `backend/sources/base.py` | Defines `FlightResult` shared across the system |
| `backend/fingerprint.py` | Pure function, no dependencies |
| `backend/main.py` | App entry point; lifespan handler wires everything together |

### Test ownership

Tests in `tests/` are written by the orchestrator before implementation. The implementing agent:
- Must not weaken or delete an orchestrator-written test to make it pass.
- May add new tests; must not modify existing ones.
- A phase is complete only when its tests pass and the full verification output is pasted into the report.

### Implementation constraints implied by the test scaffolding

- `backend/main.py` must call `backend.scheduler.search_and_store(...)` by **module reference** (i.e. `import backend.scheduler; ... backend.scheduler.search_and_store(...)`), NOT `from backend.scheduler import search_and_store`. The `client` fixture in `conftest.py` mocks the module attribute; a local import alias would bypass the mock and fire real searches during tests.
- `backend/db.py` functions read the DB path from `os.environ["AIRFARE_DB_PATH"]` via `get_db_path()`. Do not hardcode the path anywhere the tests call.
- `FlightResult` and `SearchSource` are already defined in `backend/sources/base.py` as scaffolding — do not redefine them, only add logic.
- `TrackerResponse.active` must be typed `bool` in the Pydantic model. `test_patch_tracker_sets_active_to_false` asserts `response.json()["active"] is False` — an integer `0` would fail that check.
- `GoogleFlightsSource` must handle the fli `ImportError` **inside** `search()` (or inside a module-level try/except that sets a sentinel, then checked in `search()`). The test `test_google_flights_returns_empty_list_when_fli_raises_import_error` reloads the module with `flights=None` in `sys.modules` — if the implementation uses a module-level import cached at startup, the reload may leave the module in a broken state for subsequent tests. Checking for fli availability at call time is the safe pattern.
- The lifespan shutdown handler must fully stop the APScheduler and remove all jobs. The `client` fixture creates a new `AsyncClient` per test, which starts and stops the lifespan each time — stale scheduler state between tests will cause spurious calls to `search_and_store`.

### Design decisions

- **APScheduler over cron**: dynamic pause/resume per tracker, immediate search on creation, catch-up on restart.
- **fli over alternative sources**: best data for zero API key cost. Isolated in `google_flights.py` for easy replacement.
- **SQLite**: zero-config, single file, no external server. Perfect for a single-user personal tool.
- **HTMX**: no build step, no JS framework, server-rendered. Easy to extend with React later if needed.
- **Notification table in v1 without delivery**: ensures the data model is correct before v2 adds email/webhook transport.
- **AIRFARE_DB_PATH env var**: lets tests inject a temp DB without patching module internals.

### Open questions for future

- Notification delivery method: email? Push? Webhook? Desktop notification?
- Docker deployment: single Dockerfile with uvicorn?
- Data retention: when should old snapshots be pruned?
- Authentication: if deployed publicly, add API key or basic auth?
