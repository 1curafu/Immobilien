import math
import sqlite3
import time
from typing import Optional

import httpx

from src.models import Listing

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "immo-scraper/1.0 (personal use, contact: icurafu333@gmail.com)"
NOMINATIM_RATE_LIMIT_SECONDS = 1.1  # Nominatim usage policy: max 1 req/second

SCHEMA = """
CREATE TABLE IF NOT EXISTS geocode_cache (
    query TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lon REAL NOT NULL
);
"""


def init_geocode_cache(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def geocode(conn: sqlite3.Connection, query: str) -> Optional[tuple[float, float]]:
    row = conn.execute("SELECT lat, lon FROM geocode_cache WHERE query = ?", (query,)).fetchone()
    if row is not None:
        return row[0], row[1]

    try:
        response = httpx.get(
            NOMINATIM_URL,
            params={"q": f"{query}, Switzerland", "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    results = response.json()
    time.sleep(NOMINATIM_RATE_LIMIT_SECONDS)
    if not results:
        return None

    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    conn.execute("INSERT OR REPLACE INTO geocode_cache (query, lat, lon) VALUES (?, ?, ?)", (query, lat, lon))
    conn.commit()
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bbox_around(lat: float, lon: float, radius_km: float) -> dict:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return {
        "north": lat + lat_delta,
        "south": lat - lat_delta,
        "east": lon + lon_delta,
        "west": lon - lon_delta,
    }


def filter_by_radius(
    conn: sqlite3.Connection,
    listings: list[Listing],
    center: tuple[float, float],
    radius_km: float,
) -> list[Listing]:
    center_lat, center_lon = center
    kept = []
    for listing in listings:
        coords = geocode(conn, listing.ort)
        if coords is None:
            continue
        distance = haversine_km(center_lat, center_lon, coords[0], coords[1])
        if distance <= radius_km:
            kept.append(listing)
    return kept
