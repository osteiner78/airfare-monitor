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

## Future me notes

- The `backend/sources/` directory is designed for pluggable sources. To add Amadeus: create `amadeus.py` implementing `SearchSource`, add to `__init__.py`, done.
- Notification delivery (email, push) is explicitly v2. The DB table and evaluation logic exist in v1 but no transport is wired.
- If the `fli` library breaks due to Google page changes, the fix is isolated to `backend/sources/google_flights.py`.
- **`KayakSource` (`backend/sources/kayak.py`, plan 017)**: renders `kayak.com` with headless Playwright Chromium and extracts flights via an LLM (DeepSeek, OpenAI-compatible API — key in `os.environ["DEEPSEEK_API_KEY"]`, read at call time, never at import time). `playwright`/`openai` are imported **lazily inside `_render`/`_extract`**, not at module load, specifically so unit tests can mock those two methods and exercise `search()`'s control flow without either package installed (real installs land via `RUN playwright install --with-deps chromium` in the Docker image, added Phase 5). Every extracted price is grounded against the rendered page text in `_validate` before being trusted (`historical_best_price` is `MIN` over all rows and never recomputed — a hallucinated cheap price is permanent). `_LLM_MODEL = "deepseek-chat"` / `_LLM_BASE_URL = "https://api.deepseek.com"` in `kayak.py` are an **unverified placeholder, and now confirmed wrong** (marked with a `TODO`) — the `.env` key installed in Phase 5 is an **opencode.ai Go proxy key** (opencode Go subscription includes DeepSeek V4 Flash), not a native DeepSeek API key. Per opencode's docs (fetched 2026-08-04, not independently verified against the raw API — verify live before relying on it): base URL `https://opencode.ai/zen/go/v1` (OpenAI client appends `/chat/completions`), model id likely `deepseek-v4-flash` (possibly `opencode/deepseek-v4-flash` — the two docs pages disagreed on prefixing). `kayak.py`'s current constants will fail auth against DeepSeek's real endpoint since the key isn't a DeepSeek key — **fix this before Phase 6's live verification**, it will otherwise degrade to a clean but silent `ERROR`-level `last_error` (indistinguishable from any other Kayak failure) rather than an obvious "wrong endpoint" signal. Not registered in `sources/__init__.py::get_sources()` — see "Flight source architecture" above. `search()` sets `last_error`/`last_error_level = "WARNING"` whenever `_validate` drops rows — **all** dropped (empty result, would otherwise look identical to a clean "no flights" success) or only **some** dropped (result still returned, but the message names the drop count) — because this project's observability is the `system_logs` table on `/monitor`, and `_validate`'s own `logger.warning` calls never reach it (nothing configures a stdlib logging handler that writes there). `_OVERALL_TIMEOUT_S` is derived from `_RENDER_TIMEOUT_S`/`_LLM_TIMEOUT_S` (not a bare constant) because the render step alone can consume `2 * _RENDER_TIMEOUT_S` worst-case (`page.goto`'s own timeout plus `_wait_for_results_stable`'s separate cap) before the LLM call even starts — if changing either render/LLM timeout, the overall cap recomputes automatically, but re-check the arithmetic still leaves slack.
- **Kayak wiring into the main search cycle (plan 017, Phase 3)**: `trackers.kayak_enabled` (default 0) and `trackers.kayak_next_due_at` (nullable TEXT, `NULL` = due immediately) gate a conditional Kayak call inside `search_and_store` (`backend/scheduler.py`), inserted after the existing `get_sources()` loop and before `create_snapshot` — so Kayak's rows land in the *same* snapshot as fli's, never a snapshot of their own (see the plan's "Why Kayak shares the main snapshot"). `_kayak_due(next_due_at, now)` and `_jittered_kayak_interval_minutes(base_minutes)` (±20%, floored at 1 — deliberately irregular cadence, PerimeterX is built to catch perfectly regular polling) are pure and scheduler-independent. `search_and_store` gained a `delay: bool = True` param controlling a 0–15 min pre-render `asyncio.sleep` before the Kayak call only (not the whole function) — pass `delay=False` for manual/test triggers. A Kayak failure (including an exception escaping `KayakSource.search`, which is caught defensively even though the source's own contract is never-raise) degrades to zero extra rows and logs `kayak_search_error` (distinct event name from the main loop's `search_error`, so `/monitor` can separate the two) at the source's own `last_error_level`; `kayak_next_due_at` always advances afterward, success or failure, so a blocked run can't hot-retry next tick. Toggled per-tracker via `PATCH /trackers/{id}/toggle-kayak` (`backend/pages.py`, mirrors `toggle_tracker_detail`; detail page only, no dashboard card control, no job-scheduling call since there is no separate Kayak job). **`AsyncIOScheduler()`'s library defaults already provide `max_instances=1`/`coalesce=True`** (confirmed via `AsyncIOScheduler()._job_defaults` at runtime) — the plan's job-stacking mitigation for a hung Kayak render needed no code change in `add_tracker_job`. **Production migration ran 2026-08-04** (`ALTER TABLE trackers ADD COLUMN kayak_enabled INTEGER NOT NULL DEFAULT 0;` + `ADD COLUMN kayak_next_due_at TEXT;`, backup `data/airfare.db.bak-017-phase3`); both are `ADD COLUMN`, so metadata-only and safe to run against the live DB without stopping the container. **Read these two columns with `tracker.get(...)`, never `tracker[...]`** — this service runs in Active dev, so a code edit is live instantly while a schema migration is confirmation-gated, guaranteeing a window where new code meets an old table. Reading with `[]` cost ~20 min of stalled collection across all 6 active trackers on 2026-08-04 (`KeyError: 'kayak_enabled'` raised straight out of `search_and_store`, killing the snapshot for every tracker, not just Kayak). The same applies to any future tracker column: a missing column must degrade to "feature off", never an exception on the main path.
- **`best_source` attribution (plan 017, Phase 4)**: `get_tracker_summaries` (`backend/db.py`) gained a `best_source` correlated subquery, same shape as the existing `best_flight_number` one, selecting `fp.source` from the latest snapshot ordered `price ASC, source ASC` — the `source ASC` tiebreak matters because sources sharing a snapshot means two sources quoting the same flight at the same price is the expected case, not an edge case, and a bare price-only order would flip attribution nondeterministically between identical runs. A `source_label` Jinja filter (`backend/pages.py`, alongside `currency_symbol`/`airline_code`) maps `"google_flights"` → `"Google Flights"`, `"fast_flights"` → `"Google Flights (alt)"`, `"kayak"` → `"Kayak"`, unknown values fall back to the raw string. `results_table.html` renders it in a new Source column — the `source` field was already present on every row (including reconstructed "missing" rows, which copy the full previous row dict), so this was templating only, no context-building change.
- **Template rendering bypass**: Python 3.13 + Jinja2 3.1.6 has a bug where Starlette's `Jinja2Templates.TemplateResponse` triggers `TypeError: unhashable type: 'dict'` in Jinja2's LRUCache when `env.globals` is non-empty. `backend/pages.py` works around this by using `jinja2.Environment(cache_size=0)` directly with `get_template()` + `render()` + `HTMLResponse()`. If upgrading Python/Jinja2/Starlette, try restoring `Jinja2Templates` — but verify with a quick smoke test first.
- **Router separation**: `backend/api.py` handles JSON API under `/api/*`, `backend/pages.py` handles HTML pages at `/*`. Both are included in `main.py`. The pages router also has HTMX-specific routes (toggle, form submit) that return HTML partials.
- **Chart.js time adapter issue**: CDN-loaded `chartjs-adapter-date-fns@3` fails silently on some browser/network configurations (blank chart, no JS error). The current working solution is a numeric axis (`type: "linear"`) where x-values are epoch milliseconds from `new Date(iso).getTime()`, with custom tick formatting via `ticks.callback`. The adapter CDN is NOT loaded — it was removed after repeated failures. If restoring time adapter: verify with `chart_test_time.html` first, load it BEFORE Chart.js, and confirm the adapter bundle resolves (curl shows 200 but the browser may block due to CORS or Content-Type mismatch).
- **Chart sticky top-N**: `get_sticky_top_flight_keys(tracker_id, top_n)` collects flight_keys that ever appeared in the top N cheapest at ANY snapshot. This is a union, so the total chart lines can exceed `top_n` (e.g., different flights enter/leave the top N across snapshots). The `top_n` comes from `trackers.top_n` (DB default 5, changed from plan's original 10).
- **Flight data field evolution**: `airline` field stores the full airline name (e.g. "Vueling"), `flight_number` includes the code + number (e.g. "VY 6201"). The results table shows both: Airline column = logo (falls back to name), Flight column = code+number. `airline_codes` is computed in `_map_result` but unused (dead code, harmless).
- **`flight_key` is source-independent (plan 017, Phase 1)**: format is `f"{airline}|{flight_number}|{departure_time}"` (3 parts, no `source` prefix) — `make_flight_key` in `backend/fingerprint.py`. The same physical flight quoted by two different sources (e.g. `google_flights` and `kayak`) in the same snapshot now shares one key, which is required once sources can run concurrently in one search cycle rather than as mutually-exclusive fallbacks. **Consequence: `flight_key` can legitimately repeat within a snapshot.** Every site that builds a `{flight_key: ...}` dict from `get_flight_prices_for_snapshot`'s `ORDER BY price ASC` rows must use `setdefault` (first-write-wins = cheapest), not a plain dict comprehension (last-write-wins = most expensive) — see `previous_prices`/`prev_flights`/`current_flight_map` in `pages.py::_build_detail_context`. Anywhere flight_keys are counted or color-ranked (`ordered_top_keys`, `all_flights`/`window.allFlights`, `get_sticky_top_flight_keys` in `db.py`) must dedupe to **distinct keys**, not rows — a repeated key must not consume two slots. The **results table is the deliberate exception**: it renders one `<tr>` per DB row on purpose (multi-source transparency, so the user can compare sources and pick which to book through) and must not be deduped. Production data was backfilled to the new format in the same operation as the code change (irreversible in-place migration; a `.bak-017` copy of `data/airfare.db` was taken first) — if restoring an old backup predating this, its `flight_key` values will be in the old 4-part `source|airline|flight_number|departure_time` format and need the same backfill (`UPDATE flight_prices SET flight_key = substr(flight_key, instr(flight_key, '|') + 1) WHERE (LENGTH(flight_key) - LENGTH(REPLACE(flight_key, '|', ''))) = 3;` — the `WHERE` guards against double-stripping rows already in the new format). **A seventh dedup site** (found auditing the shipped phase, not by the original grep): `history_by_key` in `_build_detail_context` merges chart points by `(flight_key, snapshot_id)` — **not** by formatted timestamp string, because two distinct snapshots can share the same second-resolution `searched_at` (e.g. two `create_snapshot` calls in quick succession) and must still render as two separate points. `get_price_history` (`backend/db.py`) selects `fp.snapshot_id` specifically to make this possible; don't drop that column if touching the query. When auditing for further sites, the question is "does this assume one row per `flight_key` per snapshot?", not "is this a dict?".
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
- **Playwright/Chromium + `--reload` orphaning (plan 017, Phase 5)**: same trap as above, heavier variant. `KayakSource._render` opens a Chromium subprocess (`async with async_playwright()` + `try/finally browser.close()`); if `--reload` fires mid-render, the detached worker's Chromium child can be orphaned too. `ps aux | grep chrome` alongside the existing `multiprocessing-fork` check when investigating stuck CPU/memory.
- **Docker/infra (plan 017, Phase 5)**: Chromium is bundled into the main image (`Dockerfile`: `RUN playwright install --with-deps chromium`, after `pip install`), not a sidecar — accepted tradeoff is a Chromium OOM takes the API down with it. Grew the image from 352MB to **2.13GB** (plan estimated 300-400MB; actual growth is dominated by `--with-deps`' apt closure — X11/Mesa/fonts libs — not just the ~300MB of Chromium/ffmpeg/headless-shell binaries themselves) — still comfortably inside the 16G free on `minnie`. `docker-compose.yml` now has `shm_size: 1gb` (was Docker's 64MB default — the standard fix for Chromium crashing in containers), `deploy.resources.limits` raised to `1.5G`/`2.0` cpus (was `256M`/`0.5`, confirmed via `docker inspect` before changing), and `env_file: .env` (first secret this project has needed). `requirements-dev.txt` (pytest etc.) is deliberately **not** baked into the image (`/srv/CLAUDE.md` convention) — running the suite in-container requires `docker exec airfare-monitor pip install -r requirements-dev.txt` first; that install doesn't persist across an image rebuild.
- **CSS accent token**: `--accent: #4a90d9` and `--accent-dark: #3a7bc8` are defined in `:root` in `app.css`. All interactive elements (buttons, links, focus rings, spinner) reference these tokens — do not add new hardcoded hex occurrences of those values.
- **Fonts**: **Geist + Geist Mono** (Google Fonts). CSS tokens `--font-sans: "Geist", ...` and `--font-mono: "Geist Mono", ...` in `:root`.
- **Dashboard tracker card**: 2-col grid (`.card-grid: minmax(150px, 0.8fr) 1.2fr`) — meta left, `.card-panel` right (chart + y-rail + last-fetch; `.card-panel` replaced the old `.card-mid`+`.card-right`). The `START/24H/3H` evo-strip is gone; replaced by a single `.trend-chip` next to CURRENT price, driven by `_primary_delta(summary)` in `backend/pages.py` — most-recent moved timeframe (`3h→24h→start`), skips `None`/`same`, green for down, red for up, with a `.trend-chip-period` label. If nothing moved, no chip renders. `_sparkline()` (pure) floors the y-band to `_MIN_SPAN_FRAC=0.06` of mean price and centers it, so tiny moves render near-flat; **no chart text labels**; two dots — current (ink, `last_*`) and all-time low (green, `low_*`, most-recent-min index). CURRENT/ALL-TIME numbers float in a y-rail at their dots' heights via `current_rail`/`alltime_rail`, de-collided by `_rail_positions` (`_MIN_GAP_FRAC=0.40`, `_RAIL_MARGIN=0.14`). `at_all_time_low` (current == `historical_best_price` == min of the full-history `get_best_price_series`) collapses the rail into one green "All-time low · now" stat; single-snapshot trackers use `.panel-fallback` (no chart). `best-price`+`filtered-tag` survive in every branch (rail-current, rail-combined, fallback) for the dashboard filter JS. Airline logo renders **only on CURRENT** — removed from `.rail-alltime` and `.fallback-alltime`. Line/area keep trend color; **dots do not**. Depart date via `format_card_date` (`%a %-d %b`, e.g. `Wed 29 Jul`) + static `· one-way`; `_format_date` unchanged. `currency_symbol` → `€`/`$`/`£` with no trailing space, `CHF ` keeps its space, unknown codes append a space. Detail page keeps the full 3-period breakdown (untouched).
