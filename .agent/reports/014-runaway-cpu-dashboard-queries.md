# 014 — Runaway CPU: expensive dashboard SQLite queries (+ orphaned reload workers)

> Investigation handoff for the coding agent. Status: **diagnosed, not fixed.** This document is both the diagnosis report and the task brief.

## Symptom

On the user's macOS workstation, Python processes from `airfare-monitor` consume massive CPU and drive the 1-min load average to ~207. Two distinct bad processes were observed:

1. **An orphaned worker** (miniconda Python 3.13, PID was 72734): `multiprocessing.spawn` fork, **PPID = 1** (parent already dead), CWD = the project, running **4h15m at ~580% CPU**, with `data/airfare.db` + `-wal` open on ~25 duplicate file descriptors. This was a stale uvicorn `--reload` server worker that got orphaned and kept spinning forever.
2. **The live dev server worker** (homebrew Python 3.14, PID 14828; PPID 14789 = the `uvicorn --reload` supervisor): climbed from ~20% to **210% CPU in ~8 minutes** with the same signature.

**Already done in this session (do not redo):** the orphan PID 72734 and its stale `resource_tracker` PID 85542 were `kill`ed. The root cause is NOT fixed — it will recur.

## Root-cause evidence

`sample 14828` showed CPU is burned across **3 aiosqlite `_connection_worker_thread`s + 3 `ThreadPoolExecutor` threads**, all in:

```
pysqlite_connection_execute → sqlite3_step → sqlite3VdbeExec → minmaxStep / sqlite3BtreeNext
```

i.e. **MIN/MAX aggregates doing full B-tree scans**. The main thread (uvloop) was mostly idle in `kevent`, with occasional `build_struct_time` (parsing returned timestamp rows).

APScheduler is NOT the trigger — there were **zero `search_start` log rows in the last 5 minutes**, so `search_and_store` is not looping. The queries come from **HTTP page/API requests** (dashboard `/`), likely amplified by HTMX auto-refresh polling.

## Data shape

- `flight_prices`: **77,317 rows** (DB file 57 MB, WAL 11 MB)
- `snapshots`: 725 rows; `trackers`: 9 (all `interval_minutes = 180`, healthy); `system_logs`: 1531
- Existing indexes only: `idx_prices_tracker_key ON flight_prices(tracker_id, flight_key)` and `idx_snapshots_tracker ON snapshots(tracker_id)`.
- **No index on `snapshots.searched_at`, no index on `flight_prices(snapshot_id, price)` or `flight_prices(tracker_id, price)`.**

## The expensive queries (in `backend/db.py`)

1. **`get_tracker_summaries()`** (≈ lines 260–341): for each tracker runs **~8 correlated subqueries**, each `MIN(fp.price)` joined to `snapshots` with `... ORDER BY searched_at DESC/ASC LIMIT 1 [OFFSET 1]` inner subqueries (`best_price`, `previous_best_price`, `historical_best_price`, `best_price_at_creation`, `best_price_24h_ago`, `best_price_3h_ago`, etc.). With 9 trackers this is O(trackers × subqueries × full-scan).
2. **`get_best_price_series()`** (≈ line 347): `SELECT s.tracker_id, MIN(fp.price) ... JOIN flight_prices fp ON fp.snapshot_id = s.id GROUP BY s.id ORDER BY s.tracker_id, s.searched_at` — full scan of all 77K rows on **every dashboard load**.
3. `get_historical_best_price()` (≈ line 436): `SELECT MIN(price) FROM flight_prices WHERE tracker_id = ?`.
4. Chart data query (≈ line 456): `ORDER BY s.id, fp.price ASC`.

## What to do

### 1. Diagnose first (don't guess)

- Run `EXPLAIN QUERY PLAN` on `get_best_price_series`, `get_tracker_summaries`, `get_historical_best_price`, and the chart query. Confirm which show `SCAN` (full scan) vs `SEARCH ... USING INDEX`.
- Time the raw queries (`sqlite3 data/airfare.db ".timer on" "<query>"`) to quantify cost.
- Identify what drives repeated requests: grep templates/JS for HTMX polling (`hx-trigger="every ..."`, `setInterval`, `/api/...` polling) on the dashboard and monitor pages. The monitor page is documented to poll every 30s; confirm the dashboard isn't doing something tighter.

### 2. Fix the query cost (primary fix)

- Add covering indexes to eliminate the full scans, e.g.:
  - `CREATE INDEX idx_snapshots_tracker_searched ON snapshots(tracker_id, searched_at);`
  - `CREATE INDEX idx_prices_snapshot_price ON flight_prices(snapshot_id, price);`
  - `CREATE INDEX idx_prices_tracker_price ON flight_prices(tracker_id, price);`
  - Add these to the schema-creation code in `backend/db.py` so fresh DBs get them, AND provide a one-off migration to apply them to the existing 57 MB DB. **Per project CLAUDE.md, schema changes / index creation on the production DB require confirming with the user first — ask before running the migration.**
- Re-run `EXPLAIN QUERY PLAN` to verify scans become index searches, and re-time.
- Consider whether `get_tracker_summaries` can be simplified (fewer correlated subqueries, or a single windowed query) — but only if it preserves exact current behavior. Orchestrator-written tests in `tests/` must not be weakened (`test_best_price.py`, `test_chart_data.py`, `test_delta.py`, `test_api.py`, `test_pages.py`).

### 3. Fix the reload-orphan amplifier (secondary)

The orphan with PPID=1 is the worst symptom: a worker stuck in a non-cancellable C-level `sqlite3_step` can't be killed cleanly when `uvicorn --reload` restarts, so it's orphaned and spins forever, and a new one accumulates on each code reload. Once queries are cheap this is largely mooted, but also:

- Document that `uvicorn --reload` should not be left running for long dev sessions against this DB, and that orphans can be found with `ps aux | grep multiprocessing-fork` (look for `PPID 1`).
- Optionally investigate setting aiosqlite/SQLite `busy_timeout` and confirm connections are properly closed on shutdown (lifespan handler) so the threadpool drains.

### 4. Verify

- `pytest tests/ -v -k "not slow"` must stay green (currently 200 passed, 1 deselected).
- Load the dashboard locally and confirm CPU stays low (no sustained multi-hundred-% spike).
- Confirm no new orphaned `multiprocessing-fork` Python processes appear after a couple of `--reload` cycles.

### 5. Document

- Write the fix outcome + verification output back into this report (or a follow-up `015-*`).
- Add a "Future me" note in `CLAUDE.md` about the new indexes and the reload-orphan gotcha.

## Constraints

- Project rules: type hints, no comments unless WHY is non-obvious, parameterized queries only, WAL mode, async via aiosqlite. Confirm before any destructive/schema action on the production DB. Do not modify existing orchestrator tests; add new ones if needed.
