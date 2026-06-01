# Airfare Tracker

## Stack

- **Backend**: Python 3.12+, FastAPI, uvicorn, APScheduler (async)
- **Database**: SQLite via aiosqlite (WAL mode)
- **Flight data**: Google Flights via `fli` library (`pip install flights`)
- **Frontend**: Server-rendered Jinja2, HTMX, Chart.js (CDN)
- **Package manager**: conda (preferred), pip as fallback

## Project structure

```
airfare-monitor/
├── backend/
│   ├── main.py              # FastAPI app, lifespan, static mount
│   ├── db.py                # aiosqlite schema + CRUD
│   ├── models.py            # Pydantic schemas
│   ├── api.py               # JSON API router (/api/*)
│   ├── pages.py             # HTML page router (/, /trackers/{id}, /monitor)
│   ├── scheduler.py         # APScheduler job management
│   ├── fingerprint.py       # flight_key generation
│   └── sources/
├── frontend/
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── tracker.html
│   │   ├── monitor.html
│   │   └── partials/
│   │       ├── add_form.html
│   │       ├── tracker_card.html
│   │       ├── tracker_list.html
│   │       ├── detail_page.html
│   │       ├── results_table.html
│   │       ├── price_badge.html
│   │       └── monitor_logs.html
│   └── static/
│       ├── app.css
│       └── charts.js
├── data/            # SQLite DB (auto-created, gitignored)
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_best_price.py
│   ├── test_chart_data.py
│   ├── test_db.py
│   ├── test_delta.py
│   ├── test_fingerprint.py
│   ├── test_logging.py
│   ├── test_normalization.py
│   ├── test_notification_log.py
│   ├── test_notifications.py
│   ├── test_pages.py
│   └── test_sources.py
├── .agent/
├── requirements.txt
├── TODO.md
└── pyproject.toml
```

## Key dependencies

```
fastapi, uvicorn, aiosqlite, apscheduler, flights, jinja2, python-multipart
```

Install: `pip install -r requirements.txt`

## Running

```bash
uvicorn backend.main:app --reload
# Dashboard at http://localhost:8000
# JSON API at http://localhost:8000/api/trackers
```

## Coding conventions

- **No comments by default** — only when the WHY is genuinely non-obvious
- **No half-finished implementations** — if out of scope, say so explicitly
- **No emojis in code or UI text** unless explicitly asked
- **Python**: type hints everywhere, dataclasses for data structures, protocols for interfaces
- **Imports**: standard library → third-party → local. One blank line between groups
- **Function naming**: `snake_case`. Descriptive names, no abbreviations
- **FastAPI**: lifespan handler for startup/shutdown, APIRouter per module, dependency injection for DB connections
- **SQLite**: always use WAL mode, parameterized queries (no f-string SQL), aiosqlite for async access
- **Frontend**: Jinja2 templates (no JS framework), HTMX for interactivity, Chart.js for charts. CSS in a single file (no framework).

## Flight source architecture

- Each source implements `SearchSource` protocol from `backend/sources/base.py`
- Sources return `list[FlightResult]` — normalized, no source-specific fields
- Each source file is self-contained: one file, one source
- New sources = new file in `sources/` + register in `__init__.py`

## Verification requirements

**A phase is complete only when its tests pass AND the full verification output is pasted into `.agent/reports/001-phase-N.md`.**

Per-phase test commands are in the plan (`.agent/plans/001-airfare-tracker.md`). Quick reference:

```bash
# Phase 1
pytest tests/test_db.py -v

# Phase 2
pytest tests/test_fingerprint.py tests/test_sources.py -v -k "not slow"

# Phase 3
pytest tests/test_api.py -v

# Phase 6
pytest tests/test_notifications.py -v

# Full suite (any phase)
pytest tests/ -v -k "not slow"
```

## Test ownership

Tests in `tests/` are written by the orchestrator before implementation. The implementing agent:
- Must **not** weaken or delete an orchestrator-written test to make it pass.
- May add new tests; must not modify existing ones.
- If a test seems wrong, flag it — do not silently change it.

## DB path convention

All DB functions read from `os.environ["AIRFARE_DB_PATH"]` with fallback `"data/airfare.db"`. Tests inject a temp path via `monkeypatch.setenv("AIRFARE_DB_PATH", ...)` in `tests/conftest.py`.

## Destructive actions — confirm first

Ask before:
- Deleting trackers or data from the database
- Dropping or altering tables (schema migration)
- Installing packages outside the project (system-level)
- Making changes outside `~/Documents/code/airfare-tracker/`
- Committing or pushing to git

## .agent directory

- `.agent/plans/` — implementation plans
- `.agent/reports/` — search reports, debug logs
- `.agent/decisions/` — architectural decision records

## Future me notes

- The `backend/sources/` directory is designed for pluggable sources. To add Amadeus: create `amadeus.py` implementing `SearchSource`, add to `__init__.py`, done.
- Notification delivery (email, push) is explicitly v2. The DB table and evaluation logic exist in v1 but no transport is wired.
- If the `fli` library breaks due to Google page changes, the fix is isolated to `backend/sources/google_flights.py`.
- **Template rendering bypass**: Python 3.13 + Jinja2 3.1.6 has a bug where Starlette's `Jinja2Templates.TemplateResponse` triggers `TypeError: unhashable type: 'dict'` in Jinja2's LRUCache when `env.globals` is non-empty. `backend/pages.py` works around this by using `jinja2.Environment(cache_size=0)` directly with `get_template()` + `render()` + `HTMLResponse()`. If upgrading Python/Jinja2/Starlette, try restoring `Jinja2Templates` — but verify with a quick smoke test first.
- **Router separation**: `backend/api.py` handles JSON API under `/api/*`, `backend/pages.py` handles HTML pages at `/*`. Both are included in `main.py`. The pages router also has HTMX-specific routes (toggle, form submit) that return HTML partials.
- **Chart.js time adapter issue**: CDN-loaded `chartjs-adapter-date-fns@3` fails silently on some browser/network configurations (blank chart, no JS error). The current working solution is a numeric axis (`type: "linear"`) where x-values are epoch milliseconds from `new Date(iso).getTime()`, with custom tick formatting via `ticks.callback`. The adapter CDN is NOT loaded — it was removed after repeated failures. If restoring time adapter: verify with `chart_test_time.html` first, load it BEFORE Chart.js, and confirm the adapter bundle resolves (curl shows 200 but the browser may block due to CORS or Content-Type mismatch).
- **Chart sticky top-N**: `get_sticky_top_flight_keys(tracker_id, top_n)` collects flight_keys that ever appeared in the top N cheapest at ANY snapshot. This is a union, so the total chart lines can exceed `top_n` (e.g., different flights enter/leave the top N across snapshots). The `top_n` comes from `trackers.top_n` (DB default 5, changed from plan's original 10).
- **Flight data field evolution**: `airline` field stores the full airline name (e.g. "Vueling"), `flight_number` includes the code + number (e.g. "VY 6201"). The results table shows both: Airline column = logo (falls back to name), Flight column = code+number. `airline_codes` is computed in `_map_result` but unused (dead code, harmless). The `flight_key` format uses full names in the second segment — uniqueness comes from `departure_time`, not the airline segment.
- **Airline logos**: results table and dashboard cards show airline logos from kiwi.com (`images.kiwi.com/airlines/64/{IATA}.png`). The IATA code is extracted from `flight_number`'s prefix by the `airline_code` Jinja filter in `pages.py` (2-char IATA designator only; multi-leg uses the first carrier). Rendering is centralized in the `airline_logo` macro (`templates/partials/macros.html`). kiwi serves a generic plane icon (HTTP 200) for unknown codes, so `onerror` can't catch those — add such codes to `LOGO_UNAVAILABLE_CODES` in `pages.py` to force the airline-name fallback. `onerror` still covers a fully blocked CDN. Dashboard cards use `best_flight_number` from the `get_tracker_summaries` correlated subquery (cheapest flight in latest snapshot).
- **Logging subsystem**: `system_logs` table in SQLite, with `insert_log(level, event, tracker_id, message)`. All search events, tracker lifecycle, and notification triggers are logged. Monitor page at `GET /monitor` with auto-refresh every 30s via HTMX polling. Log functions used: `insert_log()`, `get_recent_logs(limit)`, `get_tracker_stats()`, `get_db_stats()`.
- **`_split_timestamps(flight_dict)` helper** in `pages.py` — extracts date/time/tz from ISO 8601 departure/arrival times. Called for both current and missing flights. Use this helper if timestamp format changes.
- **`.gitignore`** has `*.db` and `data/` patterns — production database is safe from accidental commits.
- **`ensure_db_initialized` middleware** in `main.py` is a workaround for httpx 0.28 not triggering ASGI lifespan during tests. Keep it. The `_initialized_paths` set deduplicates per unique DB path.
- **Row/chart color sync**: results-table rows get a left accent border matching their chart line. Colors are assigned server-side by `_assign_chart_colors(flight_keys)` in `pages.py` (palette `CHART_COLORS`, cycled by position). The same map feeds chart datasets (`color` field, consumed by `charts.js` with the JS palette as fallback) and the table via `flight_key_colors` in the detail context. Only charted flights (`latest_top_keys`, the top-N cheapest current flights) are colored; uncharted and "missing" rows stay neutral. Rows carry `data-flight-key` (also a hook for the planned duration/stops filter).
- **Current test suite**: `pytest tests/ -v -k "not slow"` → 131 passed, 1 deselected. Test files: test_airline_logo, test_api, test_best_price, test_chart_colors, test_chart_data, test_db, test_delta, test_fingerprint, test_logging, test_normalization, test_notification_log, test_notifications, test_pages, test_sources.
