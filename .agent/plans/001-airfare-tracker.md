# 001 — Airfare Tracker v1

A personal tool to monitor flight prices over time. Create a tracker for a one-way route + date; the system periodically searches Google Flights, stores results, and shows price evolution on a chart.

---

## Architecture

```
airfare-tracker/
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
│       └── google_flights.py # fli-based implementation
├── frontend/
│   ├── templates/
│   │   ├── base.html        # Jinja2 shell, htmx + Chart.js CDN
│   │   ├── dashboard.html   # Tracker card grid + inline add form
│   │   ├── tracker.html     # Detail: chart + latest table + controls
│   │   └── partials/
│   │       ├── tracker_card.html
│   │       ├── add_form.html
│   │       ├── results_table.html
│   │       └── price_badge.html
│   └── static/
│       ├── app.css
│       └── charts.js        # Chart.js from /api/trackers/{id}/history
├── data/                    # SQLite DB auto-created at runtime
├── requirements.txt
└── pyproject.toml
```

## Database Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE trackers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,             -- IATA, e.g. GVA
    destination TEXT NOT NULL,        -- IATA, e.g. BCN
    depart_date TEXT NOT NULL,        -- YYYY-MM-DD
    return_date TEXT,                 -- NULL for v1 (v2: round-trips)
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
    flight_key TEXT NOT NULL,        -- source|airlines|flight_nums|first_dep_iso
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

Compare each flight_key in the latest snapshot against the previous one:

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
| Far-future dates | fli returns empty until inventory opens (6-10 months out) |
| Flight disappears 2x | Exclude from history response |
| DB contention | WAL mode — concurrent reads + serialized writes |
| Server restart | Rebuild all active tracker jobs, fire immediate search |

---

## Phase 1 — Scaffold + Database

Vertical slice: database exists, schema is validated, CRUD operations work from Python.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 1.1 | Create project directory tree | — | `backend/sources/`, `frontend/templates/partials/`, `frontend/static/`, `data/` |
| 1.2 | Write `pyproject.toml` | `pyproject.toml` | Python 3.12+, project metadata |
| 1.3 | Write `requirements.txt` | `requirements.txt` | fastapi, uvicorn, aiosqlite, apscheduler, flights, python-multipart |
| 1.4 | Implement `db.py` — schema DDL + init | `backend/db.py` | WAL mode, foreign keys, all three CREATE TABLE statements |
| 1.5 | Implement `db.py` — tracker CRUD | `backend/db.py` | `create_tracker`, `get_tracker`, `list_trackers`, `update_tracker`, `delete_tracker` |
| 1.6 | Implement `db.py` — snapshot + prices | `backend/db.py` | `create_snapshot`, `insert_flight_prices`, `get_latest_snapshot`, `get_previous_snapshot` |
| 1.7 | Implement `db.py` — history + summaries | `backend/db.py` | `get_price_history`, `get_tracker_summaries` |
| 1.8 | Add `data/.gitkeep` | `data/.gitkeep` | Preserve directory in version control |

### Success criteria

- `python -c "from backend.db import init_db; import asyncio; asyncio.run(init_db('data/test.db'))"` creates tables, no errors
- `python -c "from backend.db import create_tracker; ..."` creates a row, returns dict with id
- SQLite WAL journal confirmed: `PRAGMA journal_mode` returns `wal`
- Each table has the correct columns (verify with `PRAGMA table_info`)

### Risks

- aiosqlite vs sqlite3 with asyncio: aiosqlite is simpler but adds a dependency. Acceptable.
- Schema changes after v1 will require migrations. Keep schema minimal — only what we need now.

---

## Phase 2 — Flight Search Engine

Vertical slice: Google Flights search returns structured `FlightResult` objects with correct fingerprinting.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 2.1 | Implement `FlightResult` dataclass | `backend/sources/base.py` | All fields documented, with `__post_init__` validation |
| 2.2 | Implement `SearchSource` protocol | `backend/sources/base.py` | Typed protocol, async signature |
| 2.3 | Implement Google Flights source | `backend/sources/google_flights.py` | Port existing script's GF logic, remove Kiwi + report code |
| 2.4 | Handle fli import error gracefully | `backend/sources/google_flights.py` | Try/except ImportError, log warning, return `[]` |
| 2.5 | Handle search exceptions | `backend/sources/google_flights.py` | Catch exceptions (timeout, 429, parse errors), log, return `[]` |
| 2.6 | Implement `fingerprint.py` | `backend/fingerprint.py` | `make_flight_key(result: FlightResult) -> str` |
| 2.7 | Create `sources/__init__.py` | `backend/sources/__init__.py` | Export `all_sources: list[SearchSource]` |
| 2.8 | Run source factory | `backend/sources/__init__.py` | `get_sources()` — returns `[GoogleFlightsSource()]` for v1 |

### Success criteria

- `GoogleFlightsSource().search("GVA", "BCN", "2026-06-15", None, "EUR", 10)` returns `list[FlightResult]` with >0 results (real route)
- Same route returns results with correct `flight_keys`
- `GoogleFlightsSource().search("NONEXISTENT", "XXX", ...)` returns `[]` gracefully
- Fingerprint: two calls for the same date produce matching `flight_key` values for the same flight
- No `fli` import error crashes the app — graceful degradation

### Risks

- fli is a community library. If Google changes their flight page structure, fli breaks. Mitigation: isolate in `google_flights.py` so swapping sources is a single file change.
- fli is synchronous. Must be called via `asyncio.to_thread()` to avoid blocking the event loop.
- Rate limiting: Google may throttle repeated queries. 3-hour intervals should be safe but if testing triggers it, add a delay.

---

## Phase 3 — API + Scheduler

Vertical slice: FastAPI server runs, you can create trackers via HTTP, and APScheduler runs periodic searches storing results in the DB.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 3.1 | Implement `models.py` | `backend/models.py` | Pydantic: `TrackerCreate`, `TrackerUpdate`, `TrackerResponse`, `SnapshotResponse`, `HistoryResponse` |
| 3.2 | Implement scheduler module | `backend/scheduler.py` | AsyncIOScheduler init, `add_tracker_job`, `pause_job`, `resume_job`, `remove_job`, `reschedule_job` |
| 3.3 | Implement `search_and_store` | `backend/scheduler.py` | Load tracker → call sources → fingerprint → insert snapshot + prices |
| 3.4 | Implement API router — CRUD | `backend/api.py` | `POST /api/trackers`, `GET /api/trackers`, `GET /api/trackers/{id}`, `PATCH /api/trackers/{id}`, `DELETE /api/trackers/{id}` |
| 3.5 | Implement API router — search + history | `backend/api.py` | `POST /api/trackers/{id}/search`, `GET /api/trackers/{id}/history` |
| 3.6 | Integrate scheduler into CRUD | `backend/api.py` | Create → add_job + immediate search; PATCH active→0 → pause; PATCH active→1 → resume; DELETE → remove_job |
| 3.7 | Implement `main.py` | `backend/main.py` | FastAPI app, CORS (optional for same-origin), mount static, include routers, startup/shutdown lifecycle |
| 3.8 | Startup: rebuild jobs | `backend/main.py` | On startup, query active trackers, call `add_tracker_job` for each (fires immediate search) |

### Success criteria

- `uvicorn backend.main:app` starts without errors
- `curl -X POST http://localhost:8000/api/trackers -H "Content-Type: application/json" -d '{"origin":"GVA","destination":"BCN","depart_date":"2026-06-15"}'` returns 201 with tracker JSON
- After POST, DB has a tracker row, a snapshot row, and flight_prices rows
- `curl -X PATCH ... -d '{"active": false}'` pauses the scheduler job
- `curl http://localhost:8000/api/trackers` returns array with latest best price `Δ`
- `curl http://localhost:8000/api/trackers/1/history` returns flights + best_prices JSON
- Server restart: active trackers are rebuilt and search immediately fires

### Risks

- AsyncIOScheduler + FastAPI lifecycle: ensure scheduler starts after DB init and stops before app shutdown. Use FastAPI `lifespan` handler.
- Thread safety: `search_and_store` runs in a thread (fli is sync). The DB writes must use a dedicated aiosqlite connection per call or a connection pool.
- `next_run_time` for immediate search: set `next_run_time` to `datetime.now()` for the initial fire.

---

## Phase 4 — Frontend Dashboard

Vertical slice: browser shows dashboard with all trackers, inline add form works, pause/resume/delete from dashboard.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 4.1 | Implement `pages.py` | `backend/pages.py` | Jinja2Templates pointing to `frontend/templates/`, `GET /` → dashboard, `GET /trackers/{id}` → tracker |
| 4.2 | Create `base.html` shell | `frontend/templates/base.html` | htmx + Chart.js CDN, `<title>`, nav, CSS link, content block |
| 4.3 | Create `app.css` | `frontend/static/app.css` | Clean minimal styling: card grid, form, table, badges |
| 4.4 | Create `dashboard.html` | `frontend/templates/dashboard.html` | "Add Route" button, card grid, empty state |
| 4.5 | Create `add_form.html` partial | `frontend/templates/partials/add_form.html` | Inline form: origin, dest, date, currency. Submit POSTs to `/api/trackers` |
| 4.6 | Create `tracker_card.html` partial | `frontend/templates/partials/tracker_card.html` | Card: route, date, best price, Δ, active/paused badge, last checked |
| 4.7 | Wire HTMX: add tracker | `frontend/templates/dashboard.html` | `hx-post="/api/trackers"`, `hx-target="#card-grid"`, `hx-swap="beforeend"` |
| 4.8 | Wire HTMX: pause/resume/delete | `frontend/templates/dashboard.html` | PATCH to toggle active, DELETE with confirmation `hx-confirm` |

### Success criteria

- Browser at `http://localhost:8000/` shows "No trackers yet" empty state
- Filling the add form and submitting creates a tracker → card appears in grid (no page reload)
- Card shows route, date, best price, Δ, "Active" badge, last checked time
- "Pause" on a card → card shows "Paused" badge, scheduler stops
- "Delete" with confirmation → card removed, DB cascade deletes data
- Refreshing the page persists all state

### Risks

- HTMX syntax errors: test each interaction as it's wired. htmx swallows 4xx/5xx silently by default — add `hx-on::after-request` for error feedback.
- jinja2 autoescape: prices with currency symbols need `|safe` in templates or use `|e` as appropriate.
- The "last checked" time needs human-friendly formatting (e.g., "2h ago"). Server sends ISO 8601; format client-side with a small JS snippet.

---

## Phase 5 — Tracker Detail + Chart

Vertical slice: click a tracker card → detail page with Chart.js price history chart, latest results table with Δ badges, search-now button.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 5.1 | Create `tracker.html` | `frontend/templates/tracker.html` | Back link, chart container, results table, action buttons |
| 5.2 | Create `charts.js` | `frontend/static/charts.js` | Fetch `/api/trackers/{id}/history`, render Chart.js line chart |
| 5.3 | Create `results_table.html` partial | `frontend/templates/partials/results_table.html` | Table: #, airline, price, Δ badge, stops, duration |
| 5.4 | Create `price_badge.html` partial | `frontend/templates/partials/price_badge.html` | Green/red/blue/yellow badge based on Δ value |
| 5.5 | Wire HTMX: search now | `frontend/templates/tracker.html` | Button → `hx-post="/api/trackers/{id}/search"`, `hx-target="#results-table"` |
| 5.6 | Wire HTMX: pause/resume/delete | `frontend/templates/tracker.html` | PATCH toggle, DELETE with confirm + redirect to `/` |

### Success criteria

- Click a tracker card → `/trackers/1` shows the detail page
- Chart renders: X-axis = time, Y-axis = price, lines for each tracked flight + highlighted best-price line
- Latest results table shows flights sorted by price with correct Δ badges
- "Search Now" button triggers a search → results table updates + chart refreshes (no page reload)
- Pause/resume works from detail page
- Delete works with `hx-confirm` and redirects to dashboard
- Empty tracker (no results yet) shows appropriate empty state

### Risks

- Chart.js CDN: if the CDN is down, charts won't render. Add a fallback or bundle Chart.js locally. For v1, CDN is acceptable.
- Large datasets: 100+ data points per flight line can slow Chart.js canvas rendering. Keep the query efficient — limit to last 90 days of snapshots.
- Chart must resize with the window. Use Chart.js `responsive: true` + `maintainAspectRatio: false` wrapped in a div with relative sizing.
- After "Search Now", the chart data changes. The simplest approach: re-fetch `/api/trackers/{id}/history` and call `chart.data = newData; chart.update()`. Use an HTMX event trigger for this.

---

## Phase 6 — Notification Foundation + Polish

Vertical slice: notification data model exists (future-ready), all edge cases handled in UI, loading/error states present.

### Tasks

| # | Task | Files | Detail |
|---|------|-------|--------|
| 6.1 | Add notifications table to schema | `backend/db.py` | `notifications` table: `id, tracker_id, rule_type, threshold, enabled, last_fired, created_at` |
| 6.2 | Add notification CRUD to db | `backend/db.py` | `create_notification`, `list_notifications`, `delete_notification` |
| 6.3 | Add notification API endpoints | `backend/api.py` | `POST /api/notifications`, `GET /api/trackers/{id}/notifications`, `DELETE /api/notifications/{id}` |
| 6.4 | Implement notification evaluation | `backend/scheduler.py` | After `search_and_store`, evaluate rules (e.g., "price < €X" for a flight_key) |
| 6.5 | Add HTMX loading indicators | `frontend/templates/base.html` | `hx-indicator` on all interactive elements, CSS for `.htmx-request` spinner |
| 6.6 | Add error state handling | `frontend/templates/` | HTMX `hx-on::after-request` error display, toast or inline message |
| 6.7 | Responsive layout pass | `frontend/static/app.css` | CSS grid breakpoints for card grid (1 col on narrow, 2-3 on wide) |
| 6.8 | Final end-to-end smoke test | — | Create tracker → see results → wait for interval → new chart point → pause → resume → delete |

### Success criteria

- `notifications` table exists in DB schema
- API endpoints for notifications return proper responses
- After search, notification rules are evaluated (logging the result for now — delivery is v2)
- All HTMX interactions show loading spinners
- Network errors show a visible message (not silent failure)
- Layout works on narrow viewport (mobile) and wide (desktop)
- Full end-to-end flow works without errors

### Risks

- Notifications are prepared in this phase but NOT delivered (no email, no push). This is intentional — the delivery method is a separate design decision. The table + API + evaluation logic needs to be correct so v2 just plugs in the transport.
- HTMX indicator CSS can be tricky. Test on each interactive element.
- Don't over-polish. "Functional and clear" — not pixel-perfect design.

---

## Handoff Notes

### Key files to start with

| File | Purpose |
|------|---------|
| `backend/db.py` | Start here — everything depends on it. All queries in one file for v1. |
| `backend/sources/base.py` | Defines `FlightResult` shared across the system |
| `backend/fingerprint.py` | Simple pure function, no dependencies |
| `backend/main.py` | App entry point. Starts small, grows naturally. |
| `frontend/templates/base.html` | Shell for all pages. htmx + Chart.js loaded from CDN. |

### Design decisions documented in plan

- Why APScheduler over cron: dynamic pause/resume per tracker, immediate search on creation, catch-up on restart
- Why fli over alternative sources: best data for zero API key cost. Isolated in `google_flights.py` for easy replacement
- Why SQLite: zero-config, single file, no external server. Perfect for a single-user personal tool
- Why HTMX: no build step, no JS framework, server-rendered. Easy to extend with React later if needed
- Why notification DB table in v1 even without delivery: ensures the data model is right before v2 adds email/webhook transport

### Open questions for future

- Notification delivery method: email? Push? Webhook? Desktop notification?
- Docker deployment: single Dockerfile with uvicorn? Base image: `python:3.12-slim`?
- Data retention: when should old snapshots be aggregated or pruned?
- Authentication: if deployed publicly, add API key or basic auth?

### Verification checklist

After each phase, run these commands:

```
# Phase 1 verification
python -c "from backend.db import init_db; import asyncio; asyncio.run(init_db('data/test.db'))"

# Phase 2 verification (requires network)
python -c "from backend.sources.google_flights import GoogleFlightsSource; import asyncio; r = asyncio.run(GoogleFlightsSource().search('GVA','BCN','2026-06-15',None,'EUR',5)); print(f'{len(r)} results')"

# Phase 3 verification
uvicorn backend.main:app --reload
curl -X POST http://localhost:8000/api/trackers -H 'Content-Type: application/json' -d '{"origin":"GVA","destination":"BCN","depart_date":"2026-06-15"}'

# Phase 4-5 verification
open http://localhost:8000  # browse dashboard and tracker detail

# Phase 6 verification
# Manual smoke test of all interactions with error states
```
