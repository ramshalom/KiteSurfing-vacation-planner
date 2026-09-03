"""
db.py

Local SQLite persistence for trip history and reviews (UC6-UC8).
No server needed - just a file, trips.db, created next to the app.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "trips.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    inputs TEXT NOT NULL,
    candidates TEXT NOT NULL,
    selected_destination TEXT,
    refinements TEXT,
    final_plan TEXT,
    pdf_path TEXT,
    status TEXT NOT NULL DEFAULT 'Planned',
    rating_spot INTEGER,
    rating_wind INTEGER,
    rating_beach_services INTEGER,
    rating_food INTEGER,
    rating_cost INTEGER,
    rating_hotel INTEGER,
    rating_atmosphere INTEGER,
    would_return TEXT,
    review_text TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def save_trip(inputs: dict, candidates: list) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO trips (created_at, inputs, candidates, status) VALUES (?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            json.dumps(inputs),
            json.dumps(candidates),
            "Planned",
        ),
    )
    conn.commit()
    trip_id = cur.lastrowid
    conn.close()
    return trip_id


def update_selection(trip_id: int, destination_name: str, final_plan: dict):
    conn = get_conn()
    conn.execute(
        "UPDATE trips SET selected_destination = ?, final_plan = ? WHERE id = ?",
        (destination_name, json.dumps(final_plan), trip_id),
    )
    conn.commit()
    conn.close()


def update_refinement(trip_id: int, overrides: dict, final_plan: dict):
    conn = get_conn()
    conn.execute(
        "UPDATE trips SET refinements = ?, final_plan = ? WHERE id = ?",
        (json.dumps(overrides), json.dumps(final_plan), trip_id),
    )
    conn.commit()
    conn.close()


def update_pdf_path(trip_id: int, pdf_path: str):
    conn = get_conn()
    conn.execute("UPDATE trips SET pdf_path = ? WHERE id = ?", (pdf_path, trip_id))
    conn.commit()
    conn.close()


def mark_completed(trip_id: int):
    conn = get_conn()
    conn.execute("UPDATE trips SET status = 'Completed' WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()


def save_review(trip_id: int, ratings: dict, would_return: str, review_text: str):
    conn = get_conn()
    conn.execute(
        """UPDATE trips SET
            rating_spot = ?, rating_wind = ?, rating_beach_services = ?,
            rating_food = ?, rating_cost = ?, rating_hotel = ?, rating_atmosphere = ?,
            would_return = ?, review_text = ?
           WHERE id = ?""",
        (
            ratings.get("spot"), ratings.get("wind"), ratings.get("beach_services"),
            ratings.get("food"), ratings.get("cost"), ratings.get("hotel"), ratings.get("atmosphere"),
            would_return, review_text, trip_id,
        ),
    )
    conn.commit()
    conn.close()


def list_trips() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trip(trip_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_trips(trip_ids: list[int]) -> None:
    """Delete one or more trips by id (used by the History tab's checkbox-based
    delete). No-op on an empty list."""
    if not trip_ids:
        return
    conn = get_conn()
    placeholders = ", ".join("?" for _ in trip_ids)
    conn.execute(f"DELETE FROM trips WHERE id IN ({placeholders})", trip_ids)
    conn.commit()
    conn.close()


def delete_all_trips() -> None:
    """Clear the entire trip history."""
    conn = get_conn()
    conn.execute("DELETE FROM trips")
    conn.commit()
    conn.close()
