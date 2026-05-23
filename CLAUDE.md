# Airfare Tracker

## Stack

- **Backend**: Python 3.12+, FastAPI, uvicorn, APScheduler (async)
- **Database**: SQLite via aiosqlite (WAL mode)
- **Flight data**: Google Flights via `fli` library (`pip install flights`)
- **Frontend**: Server-rendered Jinja2, HTMX, Chart.js (CDN)
- **Package manager**: conda (preferred), pip as fallback

## Project structure

```
airfare-tracker/
├── backend/         # All Python code (API, DB, scheduler, sources)
├── frontend/        # Templates + static assets
├── data/            # SQLite DB (auto-created, gitignored)
├── .agent/          # Plans, decisions, reports
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
# Opens at http://localhost:8000
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

**Do not mark a phase complete until all its success criteria pass.**

After each PR/commit, run the relevant verification:

```
# Phase 1: DB schema
python -c "from backend.db import init_db; import asyncio; asyncio.run(init_db('data/test.db'))"

# Phase 2: Flight search (requires network)
python -c "from backend.sources.google_flights import GoogleFlightsSource; import asyncio; r = asyncio.run(GoogleFlightsSource().search('GVA','BCN','2026-06-15',None,'EUR',5)); print(len(r), 'results')"

# Phase 3: Server starts, API responds
uvicorn backend.main:app &  # start in background
sleep 2
curl -s http://localhost:8000/api/trackers | python -c "import sys,json; print('API ok:', json.load(sys.stdin))"
kill %1 2>/dev/null

# Phase 4-5: Full flow
# Manual smoke test in browser
```

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
