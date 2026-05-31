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
│   ├── pages.py             # HTML page router (/, /trackers/{id})
│   ├── scheduler.py         # APScheduler job management
│   ├── fingerprint.py       # flight_key generation
│   └── sources/
├── frontend/
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── tracker.html              # Phase 5
│   │   └── partials/
│   │       ├── add_form.html
│   │       ├── tracker_card.html
│   │       ├── results_table.html     # Phase 5
│   │       └── price_badge.html       # Phase 5
│   └── static/
│       ├── app.css
│       └── charts.js                  # Phase 5
├── data/            # SQLite DB (auto-created, gitignored)
├── tests/
├── .agent/
├── requirements.txt
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
- **Chart.js time adapter issue**: CDN-loaded `chartjs-adapter-date-fns@3` fails silently on some browser/network configurations (blank chart, no JS error). The fallback is a numeric axis (`type: "linear"`) where x-values are epoch milliseconds from `new Date(iso).getTime()`, with custom tick formatting via `ticks.callback`. If restoring time adapter: verify with `chart_test_time.html` first, load it BEFORE Chart.js, and confirm the adapter bundle resolves (curl shows 200 but the browser may block due to CORS or Content-Type mismatch).
- **Chart sticky top-N**: `get_sticky_top_flight_keys(tracker_id, top_n)` collects flight_keys that ever appeared in the top N cheapest at ANY snapshot. This is a union, so the total chart lines can exceed `top_n` (e.g., different flights enter/leave the top N across snapshots). The `top_n` comes from `trackers.top_n` (DB default 10, plan intended 5). To change existing trackers: `UPDATE trackers SET top_n = 5`.
