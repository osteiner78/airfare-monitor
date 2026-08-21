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
│   ├── airlines.py          # airline name -> IATA map (leaf, shared identity)
│   ├── party.py             # Party model: ages in, Google buckets out (plan 028)
│   ├── kayak_samples.py     # rendered-page sample capture (plan 018)
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
├── data/            # SQLite DB + Kayak profile/samples (auto-created, gitignored)
├── scripts/         # standalone runners (kayak_experiment.py, plan 018)
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
- `search()` takes a **single frozen `SearchQuery`** (origin, dest, dates,
  currency, top_n, party), never positional arguments (plan 028 Phase 1). Fare
  brand, baggage and cabin class are all queued behind Passengers; each would
  otherwise be another parameter and another sweep across 13 test files.
- Sources return `list[FlightResult]` — normalized, no source-specific fields
- Each source file is self-contained: one file, one source
- New sources = new file in `sources/` + register in `__init__.py` **unless
  the source is opt-in per tracker rather than global** — `KayakSource`
  (`backend/sources/kayak.py`, plan 017) is deliberately **not** registered in
  `get_sources()`; it's constructed directly wherever the per-tracker
  `kayak_enabled` flag is checked (the scheduler, once Phase 3 wires it in),
  not run unconditionally on every search cycle.

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

# Passengers (plan 028)
pytest tests/test_party.py tests/test_party_sources.py -v

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
- Making changes outside `/srv/airfare-monitor/`
- Committing or pushing to git

## .agent directory

- `.agent/plans/` — implementation plans
- `.agent/reports/` — search reports, debug logs
- `.agent/decisions/` — architectural decision records
- `.agent/context/` — background to read BEFORE working on an area (below)

## Context files — read the one matching your task

`CLAUDE.md` holds rules. The reasoning behind them — the incident, the
measurement, the rejected alternative — lives in `.agent/context/`, so this
file stays short enough to actually re-read and correct. Load the file for the
area you are touching; do not load all five.

| File | Read before touching |
|---|---|
| `.agent/context/kayak-source.md` | `sources/kayak.py`, `kayak_render.py`, `scripts/kayak_*` |
| `.agent/context/identity.md` | `fingerprint.py`, `airlines.py`, anything grouping by `flight_key` |
| `.agent/context/sources-and-scheduling.md` | `scheduler.py`, `sources/fallback.py`, blending in `pages.py` |
| `.agent/context/frontend.md` | `frontend/`, Jinja filters, context building in `pages.py` |
| `.agent/context/infrastructure.md` | `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, subprocesses |

## Rules

Each rule is enforced by a test, a report, or a context file — the pointer is
the proof. **If a rule and the code disagree, the code is right and this file
is stale: fix it here in the same commit.**

### Identity

- **`flight_key` = `airline|departure_time|arrival_time`** — no source, no
  flight number. `backend/fingerprint.py` is the **authoritative** identity
  layer: every normalisation feeding a key lives there and every other layer
  defers. A source-local normalisation is invisible to identity and stops
  applying the moment another source appears. → `identity.md`,
  `tests/test_fingerprint.py`
- **A `flight_key` can legitimately repeat within one snapshot** (two sources,
  one flight). Building a `{key: row}` dict from price-ordered rows must use
  `setdefault` (first write = cheapest); anything counting or colour-ranking
  keys must dedupe to **distinct keys**. The results table is the deliberate
  exception — one `<tr>` per row, never deduped. → `identity.md`,
  `tests/test_chart_data.py`
- **Adding a name to `AIRLINE_NAME_TO_CODE` changes `flight_key` for every row
  of that carrier.** It is not a display-only table. A map edit means re-running
  `scripts/backfill_019_flight_keys.py <db>` — never a hand-written SQL
  equivalent, which cannot consult the map. → `identity.md`
- **Party is not part of identity.** The same flight priced for 1 or 4
  travellers is one flight.

### Sources and scheduling

- **`search()` takes one frozen `SearchQuery`**, never positional arguments.
  → "Flight source architecture" above
- **`last_error` / `last_error_level` is the ONLY channel `/monitor` sees.**
  `logger.warning` never reaches `system_logs`. Any path that returns fewer rows
  than expected — including a caught `ImportError` — must set it, or a failure
  looks byte-identical to a success. → `sources-and-scheduling.md`,
  `tests/test_source_degradation.py`
- **Read migration-added tracker columns with `.get(...)`, never `[...]`.**
  Active dev guarantees a window where new code meets an un-migrated table; a
  missing column must degrade to "feature off". Reading with `[]` cost ~20 min
  of stalled collection across all 6 trackers on 2026-08-04. →
  `sources-and-scheduling.md`
- **Per-source opt-in lives in `tracker_sources`**, not in tracker columns.
  Only opt-in *browser* sources get rows — `FallbackSource` is a composite whose
  secondary runs only when the primary is empty, so `google_flights` /
  `fast_flights` are not independently schedulable. →
  `sources-and-scheduling.md`
- **`search_and_store(tracker_id, delay)` has no default** — every call site
  chooses. Manual triggers pass `delay=False`; only the scheduled job passes
  `True`. A forgotten `delay` blocks an HTTP response for up to 15 minutes. →
  `tests/test_kayak_scheduling.py`
- **Sources are blended per source at READ time, and nothing is written back.**
  Carrying rows forward into new snapshots would fabricate chart points, and
  `historical_best_price` is `MIN` over all rows and never recomputed. →
  `sources-and-scheduling.md`, `tests/test_blended_sources.py`
- **The party model carries AGES and derives COUNTS.** Kayak's URL takes ages;
  both Google-side libraries take counts by bucket and no age at all.
  `infants_on_lap` is explicit because no age can imply it. Cross-source price
  agreement is only tight for **adults-only** parties. `fast_flights.Passengers`
  defaults every field to `0` — never construct it empty. →
  `sources-and-scheduling.md`, `tests/test_party.py`
- **Prices are stored as the party TOTAL plus `passenger_count`; party is
  FROZEN after tracker creation.** Kayak prints per person and is multiplied at
  extraction — forget it and Kayak wins every headline permanently. →
  `sources-and-scheduling.md`, `tests/test_party_sources.py`
- **Default tracker interval is 60 min** (`DEFAULT_INTERVAL_MINUTES` in `db.py`
  is the single source of truth). ~30 min is the floor: below that the
  pre-render jitter stops fitting inside one tick. →
  `sources-and-scheduling.md`
- The `backend/sources/` directory is designed for pluggable sources. To add
  Amadeus: create `amadeus.py` implementing `SearchSource`, add to
  `__init__.py`, done.
- If the `fli` library breaks due to Google page changes, the fix is isolated to
  `backend/sources/google_flights.py`.
- Notification delivery (email, push) is explicitly v2. The DB table and
  evaluation logic exist in v1 but no transport is wired.

### Kayak

- **Never weaken or carve out `_validate`'s grounding checks.** Every extracted
  price, clock time and airline must appear in the rendered page text.
  `historical_best_price` is `MIN` over all rows and never recomputed, so one
  hallucinated cheap price is permanent. If the model returns an IATA code where
  the page prints a full name, the fix is **prompt-side**. →
  `kayak-source.md`, `tests/test_kayak_source.py`
- **`data/kayak-profile` is load-bearing operational state.** Deleting it
  silently reverts Kayak to USD, after which every search refuses (safely, but
  the feature is inert). Re-run `scripts/kayak_currency_picker.py set`. It is
  also Chromium-locked: **one render at a time, process-wide.** →
  `kayak-source.md`
- **The timeout budget is an explicit SUM of the waits the child performs**, not
  a factor. `tests/test_kayak_timeout_budget.py` reads the waits out of
  `kayak_render.py`'s source, so adding one fails the suite. →
  `kayak-source.md`
- **A new block-strip uses `_strip_blocks`**, not a hand-rolled scan loop. Each
  existing wrapper's docstring is evidence from a separate production incident —
  keep them. → `kayak-source.md`, `tests/test_kayak_placements.py`
- **Kayak runs on 4 trackers and each is real traffic against a bot-detecting
  site plus one LLM call per cycle.** Add deliberately. → `kayak-source.md`
- **`patchright` / `openai` are imported lazily inside `_render` / `_extract`**
  so unit tests can mock them without the packages installed. The LLM key is
  read from `os.environ["DEEPSEEK_API_KEY"]` **at call time**, never at import.
  → `kayak-source.md`

### Infrastructure

- **`fork()` is unsafe in the ASGI worker.** uvloop's
  `asyncio.create_subprocess_exec` forks, and the worker holds live
  `curl_cffi.Curl` objects that SIGSEGV in the child before `execve`. Any
  subprocess spawn from this app must use `os.posix_spawn` (that is what
  `_spawn_render_worker` does). → `infrastructure.md`,
  `.agent/reports/021-phase-1-rootcause.md`
- **Xvfb is not supervised**, and its stale lock survives a container restart —
  `docker-entrypoint.sh` clears it by pid. → `infrastructure.md`
- **Do not leave `uvicorn --reload` running unattended against a large DB** —
  a reload mid-query orphans the worker (`ps aux | grep multiprocessing-fork`),
  and mid-render it orphans Chromium (`grep chrome`). → `infrastructure.md`
- **Two `flight_prices` indexes are critical** and must exist after any restore:
  `idx_prices_snapshot_price`, `idx_prices_tracker_price`. →
  `infrastructure.md`
- **Keep `ensure_db_initialized` middleware in `main.py`** — httpx 0.28 does not
  trigger ASGI lifespan during tests. → `infrastructure.md`
- `.gitignore` covers `*.db` and `data/` — the production database is safe from
  accidental commits.

### Frontend

- **`backend/pages.py` renders via `jinja2.Environment(cache_size=0)` directly,
  not Starlette's `Jinja2Templates`** — a Python 3.13 + Jinja2 3.1.6 LRUCache
  bug. Try restoring it only with a smoke test. → `frontend.md`
- **The Chart.js time adapter is NOT loaded**; the x-axis is numeric (epoch ms).
  It failed silently on some browser/network configs. → `frontend.md`
- **`flight_key` on each chart dataset is load-bearing** — `filters.js` uses it
  to re-add sticky flights missing from the current snapshot. Drop it and the
  bug returns silently. → `frontend.md`,
  `tests/test_chart_sticky_missing.py`
- **`_relative_minutes` (`pages.py`) and `base.html::updateRelativeTimes()` must
  agree bucket for bucket.** Change one, change both. → `frontend.md`,
  `tests/test_filters.py`
- **Router separation**: `backend/api.py` serves JSON under `/api/*`,
  `backend/pages.py` serves HTML at `/*` plus HTMX partials.
- **There is no JS test runner**, so every frontend invariant above is verified
  by hand. Adding one is the opening move of the expandable-row UI work
  (`TODO.md`).

### Test suite

- **`pytest tests/ -v -k "not slow"` → 539 passed, 54 failed, 3 deselected.**
  The 54 failures are **deliberate**: plan 028 landed its specs before
  implementation, so each is unwritten code, not a regression. Green-only while
  implementing: `--ignore=tests/test_search_query.py --ignore=tests/test_party.py
  --ignore=tests/test_tracker_sources.py --ignore=tests/test_party_sources.py
  --ignore=tests/test_intern_text.py --ignore=tests/test_runlength.py`.
  In `test_intern_text.py` and `test_runlength.py` most tests **pass today by
  design** — interning and run-length are lossless, so those assertions are
  anchors that must survive untouched.
