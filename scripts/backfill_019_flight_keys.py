"""One-shot backfill: recompute every flight_prices.flight_key under plan 019's
identity scheme (airline|departure_time|arrival_time).

Calls make_flight_key itself rather than reimplementing it in SQL, so the
stored keys agree with the keys the running code generates by construction --
SQLite's LOWER() is ASCII-only without ICU and TRIM() does not collapse
internal whitespace, so a hand-written SQL equivalent only holds while the
data happens to stay clean ASCII (plan 019 task 2.4).

Run with the container stopped, after taking a backup. Idempotent: rows
already in the new format are rewritten to the identical value.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.fingerprint import make_flight_key  # noqa: E402
from backend.sources.base import FlightResult  # noqa: E402

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/airfare.db"


def _key(airline, departure_time, arrival_time) -> str:
    return make_flight_key(
        FlightResult(
            source="",
            price=0.0,
            currency="",
            duration_min=None,
            stops=0,
            airline=airline or "",
            flight_number="",
            departure_time=departure_time or "",
            arrival_time=arrival_time or "",
            legs_json="[]",
            booking_url="",
        )
    )


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT id, airline, departure_time, arrival_time, flight_key FROM flight_prices"
    ).fetchall()

    updates = []
    unchanged = 0
    for row_id, airline, departure_time, arrival_time, existing in rows:
        new_key = _key(airline, departure_time, arrival_time)
        if new_key == existing:
            unchanged += 1
        else:
            updates.append((new_key, row_id))

    print(f"rows read:      {len(rows)}")
    print(f"already correct:{unchanged:>7}")
    print(f"to rewrite:     {len(updates)}")

    db.executemany("UPDATE flight_prices SET flight_key = ? WHERE id = ?", updates)
    db.commit()

    bad = db.execute(
        "SELECT COUNT(*) FROM flight_prices WHERE flight_key IS NULL OR flight_key = ''"
    ).fetchone()[0]
    distinct = db.execute("SELECT COUNT(DISTINCT flight_key) FROM flight_prices").fetchone()[0]
    print(f"null/empty keys after: {bad}")
    print(f"distinct keys after:   {distinct}")
    db.close()


if __name__ == "__main__":
    main()
