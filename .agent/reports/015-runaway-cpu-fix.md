# 015 — Runaway CPU fix: covering indexes on flight_prices

Follows up on `014-runaway-cpu-dashboard-queries.md`.

## Diagnosis results

### HTMX polling audit

Only the monitor page polls (every 30s, for system logs). Dashboard has no auto-refresh: the
"Refresh All" button is manual-only. `base.html` `setInterval` only updates relative timestamps
client-side with no HTTP request. So polling is not the amplifier — the raw query cost is.

### EXPLAIN QUERY PLAN (before fix)

**`get_best_price_series`:**
```
SCAN fp                              ← full scan of all 77,317 flight_prices rows
SEARCH s USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
```

**`get_historical_best_price` / `best_price` correlated subquery:**
```
SEARCH fp2 USING INDEX idx_prices_tracker_key (tracker_id=?)
```
The `(tracker_id, flight_key)` index narrows to the tracker but still scans all rows for that
tracker to compute MIN(price) — it's not a covering index for price.

### Timing (before)

- `get_best_price_series`: ~60 ms (sqlite3 CLI, cold)
- `get_tracker_summaries` key subqueries: ~300 ms total
- Combined on every dashboard page load: ~360 ms minimum, worse under concurrency

At 3 aiosqlite thread-pool connections handling concurrent requests, each doing 77K-row scans
with `sqlite3VdbeExec → minmaxStep / sqlite3BtreeNext`, CPU saturated to 200%+.

### EXPLAIN QUERY PLAN (after fix)

**`get_best_price_series`:**
```
SCAN s                                             ← only 725 snapshots rows
SEARCH fp USING COVERING INDEX idx_prices_snapshot_price (snapshot_id=?)
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
```
Full scan eliminated. SQLite now iterates snapshots and does an O(log n) covering-index lookup
per snapshot; MIN(price) is the first entry in the index leaf — zero table rows read.

**`best_price` correlated subquery (get_tracker_summaries):**
```
SEARCH fp USING INDEX idx_prices_snapshot_price (snapshot_id=?)
SCALAR SUBQUERY 1: SEARCH snapshots USING INDEX idx_snapshots_tracker (tracker_id=?)
REUSE SUBQUERY 1
```
Now uses the snapshot_price covering index for the MIN(price) lookup. SQLite also caches the
scalar subquery result (REUSE SUBQUERY 1).

**`get_historical_best_price`:**
```
SEARCH fp2 USING COVERING INDEX idx_prices_tracker_price (tracker_id=?)
```
MIN(price) per tracker now resolved entirely within the index, no table access.

### Timing (after)

- `get_best_price_series`: ~22 ms (~3× faster)
- `get_tracker_summaries` subqueries: significantly reduced (not re-timed due to test DB setup
  complexity, but the dominant full-scan path is eliminated)

## Fix

Two indexes added to `_SCHEMA` in `backend/db.py`:

```sql
CREATE INDEX IF NOT EXISTS idx_prices_snapshot_price ON flight_prices(snapshot_id, price);
CREATE INDEX IF NOT EXISTS idx_prices_tracker_price  ON flight_prices(tracker_id, price);
```

Fresh databases will get them automatically via `init_db()`. Existing production DB needs a
one-off migration (see below).

## Migration SQL (for production DB — requires user confirmation)

```sql
CREATE INDEX IF NOT EXISTS idx_prices_snapshot_price ON flight_prices(snapshot_id, price);
CREATE INDEX IF NOT EXISTS idx_prices_tracker_price  ON flight_prices(tracker_id, price);
```

Run as:
```bash
sqlite3 data/airfare.db "
CREATE INDEX IF NOT EXISTS idx_prices_snapshot_price ON flight_prices(snapshot_id, price);
CREATE INDEX IF NOT EXISTS idx_prices_tracker_price  ON flight_prices(tracker_id, price);
"
```
On a 57 MB DB with 77K rows, this takes a few seconds and is non-destructive (read-only for
existing data). It can be reversed with `DROP INDEX` if needed.

## Reload-orphan warning

`uvicorn --reload` spawns a child worker per code change. If a worker is mid-query (C-level
`sqlite3_step` is non-interruptible), the OS cannot kill it cleanly; it detaches with PPID=1
and keeps spinning. Once queries are fast (ms, not hundreds of ms) the window for this is
negligible. To find orphans: `ps aux | grep multiprocessing-fork` — PPID=1 with
`data/airfare.db` in the fd list confirms a stale worker. Kill with `kill <pid>`.

## Verification

```
pytest tests/ -v -k "not slow"
200 passed, 1 deselected in 3.29s
```

All tests green. No tests modified.
