import sqlite3
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS scraper_failures (
    name TEXT PRIMARY KEY,
    failed_at TEXT NOT NULL
);
"""


def init_cooldown(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def record_failure(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO scraper_failures (name, failed_at) VALUES (?, datetime('now'))",
        (name,),
    )
    conn.commit()


def clear_failure(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM scraper_failures WHERE name = ?", (name,))
    conn.commit()


def hours_since_failure(conn: sqlite3.Connection, name: str) -> Optional[float]:
    row = conn.execute(
        "SELECT (julianday('now') - julianday(failed_at)) * 24 FROM scraper_failures WHERE name = ?",
        (name,),
    ).fetchone()
    return row[0] if row else None


def is_in_cooldown(conn: sqlite3.Connection, name: str, cooldown_hours: float) -> bool:
    hours = hours_since_failure(conn, name)
    return hours is not None and hours < cooldown_hours
