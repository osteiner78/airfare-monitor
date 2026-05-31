import os
from typing import Any

import aiosqlite


def get_db_path() -> str:
    return os.environ.get("AIRFARE_DB_PATH", "data/airfare.db")


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS trackers (
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

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    searched_at TEXT NOT NULL DEFAULT (datetime('now')),
    results_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flight_prices (
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

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    threshold REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id INTEGER,
    tracker_id INTEGER NOT NULL,
    triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
    best_price REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_tracker_key ON flight_prices(tracker_id, flight_key);
CREATE INDEX IF NOT EXISTS idx_snapshots_tracker ON snapshots(tracker_id, searched_at);
"""


async def init_db(path: str | None = None) -> None:
    db_path = path or get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return dict(row)


async def create_tracker(**kwargs: Any) -> dict:
    db_path = get_db_path()
    cols = list(kwargs.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    values = [kwargs[c] for c in cols]

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        async with db.execute(
            f"INSERT INTO trackers ({col_names}) VALUES ({placeholders})",
            values,
        ) as cur:
            row_id = cur.lastrowid
        await db.commit()
        async with db.execute("SELECT * FROM trackers WHERE id = ?", (row_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def get_tracker(tracker_id: int) -> dict | None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


async def list_trackers() -> list:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM trackers ORDER BY id") as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_tracker(tracker_id: int, **kwargs: Any) -> dict:
    db_path = get_db_path()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [tracker_id]

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            f"UPDATE trackers SET {set_clause} WHERE id = ?",
            values,
        )
        await db.commit()
        async with db.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def delete_tracker(tracker_id: int) -> None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
        await db.commit()


async def create_snapshot(tracker_id: int, results_count: int = 0) -> dict:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        async with db.execute(
            "INSERT INTO snapshots (tracker_id, results_count) VALUES (?, ?)",
            (tracker_id, results_count),
        ) as cur:
            row_id = cur.lastrowid
        await db.commit()
        async with db.execute("SELECT * FROM snapshots WHERE id = ?", (row_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def insert_flight_prices(snapshot_id: int, tracker_id: int, prices: list) -> None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executemany(
            """INSERT INTO flight_prices
               (snapshot_id, tracker_id, flight_key, source, price, currency,
                duration_min, stops, airline, flight_number,
                departure_time, arrival_time, legs_json, booking_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    snapshot_id,
                    tracker_id,
                    p["flight_key"],
                    p["source"],
                    p["price"],
                    p["currency"],
                    p.get("duration_min"),
                    p.get("stops"),
                    p.get("airline"),
                    p.get("flight_number"),
                    p.get("departure_time"),
                    p.get("arrival_time"),
                    p.get("legs_json"),
                    p.get("booking_url"),
                )
                for p in prices
            ],
        )
        await db.commit()


async def get_latest_snapshot(tracker_id: int) -> dict | None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM snapshots WHERE tracker_id = ? ORDER BY searched_at DESC LIMIT 1",
            (tracker_id,),
        ) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def get_previous_snapshot(tracker_id: int) -> dict | None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM snapshots WHERE tracker_id = ? ORDER BY searched_at DESC LIMIT 1 OFFSET 1",
            (tracker_id,),
        ) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def get_flight_prices_for_snapshot(snapshot_id: int) -> list:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM flight_prices WHERE snapshot_id = ? ORDER BY price ASC",
            (snapshot_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_price_history(tracker_id: int) -> list:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT fp.flight_key, fp.price, fp.currency, fp.airline,
                      fp.flight_number, fp.departure_time, fp.arrival_time,
                      fp.duration_min, fp.stops, s.searched_at
               FROM flight_prices fp
               JOIN snapshots s ON fp.snapshot_id = s.id
               WHERE fp.tracker_id = ?
               ORDER BY s.searched_at ASC""",
            (tracker_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_tracker_summaries() -> list:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT t.*,
                      (SELECT MIN(fp.price)
                       FROM flight_prices fp
                       JOIN snapshots s ON fp.snapshot_id = s.id
                       WHERE fp.tracker_id = t.id
                         AND s.id = (SELECT id FROM snapshots
                                     WHERE tracker_id = t.id
                                     ORDER BY searched_at DESC LIMIT 1)
                      ) AS best_price,
                      (SELECT MIN(fp.price)
                       FROM flight_prices fp
                       JOIN snapshots s ON fp.snapshot_id = s.id
                       WHERE fp.tracker_id = t.id
                         AND s.id = (SELECT id FROM snapshots
                                     WHERE tracker_id = t.id
                                     ORDER BY searched_at DESC LIMIT 1 OFFSET 1)
                      ) AS previous_best_price,
                      (SELECT searched_at FROM snapshots
                       WHERE tracker_id = t.id
                       ORDER BY searched_at DESC LIMIT 1
                      ) AS last_searched_at,
                      (SELECT COUNT(*) FROM notification_log
                       WHERE tracker_id = t.id
                         AND triggered_at > datetime('now', '-1 day')
                      ) AS recent_alerts
               FROM trackers t
               ORDER BY t.id""",
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def create_notification(tracker_id: int, rule_type: str, threshold: float) -> dict:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        async with db.execute(
            "INSERT INTO notifications (tracker_id, rule_type, threshold) VALUES (?, ?, ?)",
            (tracker_id, rule_type, threshold),
        ) as cur:
            row_id = cur.lastrowid
        await db.commit()
        async with db.execute("SELECT * FROM notifications WHERE id = ?", (row_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def list_notifications(tracker_id: int) -> list:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM notifications WHERE tracker_id = ? ORDER BY id",
            (tracker_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def delete_notification(notification_id: int) -> None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
        await db.commit()


async def get_notification(notification_id: int) -> dict | None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def insert_notification_log(notification_id: int | None, tracker_id: int, best_price: float) -> dict:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        async with db.execute(
            "INSERT INTO notification_log (notification_id, tracker_id, best_price) VALUES (?, ?, ?)",
            (notification_id, tracker_id, best_price),
        ) as cur:
            row_id = cur.lastrowid
        await db.commit()
        async with db.execute("SELECT * FROM notification_log WHERE id = ?", (row_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def get_recent_alerts_count(tracker_id: int) -> int:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM notification_log WHERE tracker_id = ? AND triggered_at > datetime('now', '-1 day')",
            (tracker_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def get_historical_best_price(tracker_id: int) -> float | None:
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT MIN(price) FROM flight_prices WHERE tracker_id = ?",
            (tracker_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] is not None else None
