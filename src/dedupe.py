import sqlite3

from src.models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_listings (
    id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def filter_new(conn: sqlite3.Connection, listings: list[Listing]) -> list[Listing]:
    if not listings:
        return []
    ids = [listing.id for listing in listings]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT id FROM seen_listings WHERE id IN ({placeholders})", ids).fetchall()
    seen_ids = {row[0] for row in rows}
    return [listing for listing in listings if listing.id not in seen_ids]


def mark_seen(conn: sqlite3.Connection, listings: list[Listing]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO seen_listings (id) VALUES (?)",
        [(listing.id,) for listing in listings],
    )
    conn.commit()
