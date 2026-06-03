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
│       ├── charts.js
│       └── filters.js
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
│   ├── test_sources.py
│   └── test_filters.py
├── .agent/
├── requirements.txt
├── TODO.md
└── pyproject.toml
```

## Key dependencies

```
fastapi, uvicorn, aiosqlite, apscheduler, flights, jinja2, python-multipart
```

Install (runtime): `pip install -r requirements.txt`
Install (dev/tests): `pip install -r requirements-dev.txt`

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
- **Airline logos**: served via `GET /airline-logo/{code}` proxy in `pages.py`. First request fetches from `images.kiwi.com/airlines/128/{IATA}.png` and stores in `_logo_cache` (in-memory dict); subsequent requests return instantly from cache with `Cache-Control: public, max-age=86400`. The `airline_logo` macro (`templates/partials/macros.html`) uses `/airline-logo/{code}`. The `airline_code` Jinja filter extracts the 2-char IATA prefix from `flight_number`. kiwi serves a generic plane icon (HTTP 200) for unknown codes — add such codes to `LOGO_UNAVAILABLE_CODES` in `pages.py` to force the airline-name fallback. `onerror` handles a fully blocked CDN. Dashboard cards use `best_flight_number` from the `get_tracker_summaries` correlated subquery.
- **Logging subsystem**: `system_logs` table in SQLite, with `insert_log(level, event, tracker_id, message)`. All search events, tracker lifecycle, and notification triggers are logged. Monitor page at `GET /monitor` with auto-refresh every 30s via HTMX polling. Log functions used: `insert_log()`, `get_recent_logs(limit)`, `get_tracker_stats()`, `get_db_stats()`.
- **`_split_timestamps(flight_dict)` helper** in `pages.py` — extracts date/time/tz from ISO 8601 departure/arrival times. Called for both current and missing flights. Use this helper if timestamp format changes.
- **`.gitignore`** has `*.db` and `data/` patterns — production database is safe from accidental commits.
- **`ensure_db_initialized` middleware** in `main.py` is a workaround for httpx 0.28 not triggering ASGI lifespan during tests. Keep it. The `_initialized_paths` set deduplicates per unique DB path.
- **Row/chart color sync**: results-table rows get a left accent border matching their chart line. Colors are assigned server-side by `_assign_chart_colors(flight_keys)` in `pages.py` (palette `CHART_COLORS`, cycled by position). Color rule is **price-rank**: cheapest current flight → palette[0]. This is reproducible client-side. The same map feeds chart datasets (`color` field) and the table via `flight_key_colors`. Only top-N current flights are colored; uncharted and "missing" rows stay neutral. Rows carry `data-flight-key`, `data-stops`, `data-duration` attributes.
- **Tracker filter sidebar (stops + duration + airline)**: client-side. Server ships `window.allFlights` (full history + `stops`/`duration_min`/`airline` for every current non-missing flight) and an inert sidebar with data-bounded controls; `frontend/static/filters.js` makes it live. On each change (and `htmx:afterSwap`) `applyFilters()` filters `allFlights`, recomputes the price-rank top-N, assigns `CHART_COLORS` by rank (cheapest = palette[0]), redraws via `window.renderPriceChart` (extracted from `charts.js`), greys filtered rows (`.row-filtered`, wins over `.row-colored`), and recolors survivors. Null `duration_min` passes the duration filter. Airline filter (plan 011): client-side, groups current non-missing flights by `flight.airline` name (null → "Unknown"/value `""`), all-checked-by-default with none-checked = empty result, sorted by best price asc. Server emits an `airlines` facet (name/count/best_price) + `airline` on each `window.allFlights` entry + `data-airline` per row; `filters.js` adds one `selectedAirlines` predicate to `passes()`. Not persisted. Filter state persistence (URL/localStorage) is the deferred next step.
- **Current test suite**: `pytest tests/ -v -k "not slow"` → 200 passed, 1 deselected (test files: `ls tests/`).
- **DB indexes (flight_prices)**: Two covering indexes are critical for dashboard performance. `idx_prices_snapshot_price ON flight_prices(snapshot_id, price)` is used by `get_best_price_series` (turns a 77K-row full scan into 725 snapshot-keyed index lookups) and by the `best_price`/`previous_best_price` correlated subqueries in `get_tracker_summaries`. `idx_prices_tracker_price ON flight_prices(tracker_id, price)` is used by `get_historical_best_price` (covering index — MIN resolved in-index, no table access). Both are in `_SCHEMA`. If restoring from a backup DB that predates these, run: `sqlite3 data/airfare.db "CREATE INDEX IF NOT EXISTS idx_prices_snapshot_price ON flight_prices(snapshot_id, price); CREATE INDEX IF NOT EXISTS idx_prices_tracker_price ON flight_prices(tracker_id, price);"`.
- **uvicorn --reload and orphaned workers**: `uvicorn --reload` spawns a new worker on each code change. If a worker is mid-query when the reload fires, the C-level `sqlite3_step` is non-interruptible; the OS detaches the worker (PPID becomes 1) and it spins forever. With fast queries (ms range) the window is negligible, but with slow un-indexed queries it caused 580% CPU for 4h+. Do not leave `uvicorn --reload` running unattended against a large DB. Orphans: `ps aux | grep multiprocessing-fork` — PPID=1 + `data/airfare.db` in fds = stale worker, kill it.
- **CSS accent token**: `--accent: #4a90d9` and `--accent-dark: #3a7bc8` are defined in `:root` in `app.css`. All interactive elements (buttons, links, focus rings, spinner) reference these tokens — do not add new hardcoded hex occurrences of those values.
- **Fonts**: **Geist + Geist Mono** (Google Fonts). CSS tokens `--font-sans: "Geist", ...` and `--font-mono: "Geist Mono", ...` in `:root`.
- **Dashboard tracker card**: 2-col grid (`.card-grid: minmax(150px, 0.8fr) 1.2fr`) — meta left, `.card-panel` right (chart + y-rail + last-fetch; `.card-panel` replaced the old `.card-mid`+`.card-right`). The `START/24H/3H` evo-strip is gone; replaced by a single `.trend-chip` next to CURRENT price, driven by `_primary_delta(summary)` in `backend/pages.py` — most-recent moved timeframe (`3h→24h→start`), skips `None`/`same`, green for down, red for up, with a `.trend-chip-period` label. If nothing moved, no chip renders. `_sparkline()` (pure) floors the y-band to `_MIN_SPAN_FRAC=0.06` of mean price and centers it, so tiny moves render near-flat; **no chart text labels**; two dots — current (ink, `last_*`) and all-time low (green, `low_*`, most-recent-min index). CURRENT/ALL-TIME numbers float in a y-rail at their dots' heights via `current_rail`/`alltime_rail`, de-collided by `_rail_positions` (`_MIN_GAP_FRAC=0.40`, `_RAIL_MARGIN=0.14`). `at_all_time_low` (current == `historical_best_price` == min of the full-history `get_best_price_series`) collapses the rail into one green "All-time low · now" stat; single-snapshot trackers use `.panel-fallback` (no chart). `best-price`+`filtered-tag` survive in every branch (rail-current, rail-combined, fallback) for the dashboard filter JS. Airline logo renders **only on CURRENT** — removed from `.rail-alltime` and `.fallback-alltime`. Line/area keep trend color; **dots do not**. Depart date via `format_card_date` (`%a %-d %b`, e.g. `Wed 29 Jul`) + static `· one-way`; `_format_date` unchanged. `currency_symbol` → `€`/`$`/`£` with no trailing space, `CHF ` keeps its space, unknown codes append a space. Detail page keeps the full 3-period breakdown (untouched).
