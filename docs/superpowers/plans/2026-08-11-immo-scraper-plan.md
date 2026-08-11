# Immo-Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python pipeline that scrapes 4 Swiss rental portals (Flatfox, Homegate, ImmoScout24, Comparis) daily, filters by price/radius, dedupes against a local SQLite store, and emails new hits sorted by price ascending.

**Architecture:** Each portal has an isolated scraper module exposing `scrape(config: SearchConfig, geocode_conn) -> list[Listing]`. `main.py` calls each in turn (catching per-scraper errors), merges results, applies a Haversine radius filter (ground truth, using a Nominatim-backed geocode cache) and price/room filters, dedupes against `seen_listings.db`, sorts by price, and emails via Gmail SMTP. Flatfox uses a public JSON API (`httpx` only); Homegate/ImmoScout24/Comparis are DataDome-protected and require a real (non-flagged-headless) Playwright Chromium.

**Tech Stack:** Python 3.11+, httpx, playwright, geopy-free hand-rolled Nominatim client (see rationale in Task 3), PyYAML, python-dotenv, pytest + pytest-mock, smtplib, sqlite3, GitHub Actions.

## Global Constraints

- Python 3.11+, all new code under `src/`, all tests under `tests/`.
- No live network calls inside `pytest` — every test that would otherwise hit Nominatim, a portal, or SMTP must mock it or use a pre-seeded SQLite cache.
- Rate-limit: `config.yaml`'s `scraper.rate_limit_sekunden` (default 2s) is applied after every scraper run; Nominatim calls additionally sleep 1.1s per live geocode (its usage policy caps at 1 req/sec).
- wgzimmer.ch is explicitly **out of scope** — it reCAPTCHA-gates every search request; no code in this plan targets it. It is documented in the README as a manual-check source only.
- Every scraper wraps its own failures in `ScraperError`; a single scraper failing must never stop the others or the email from being sent.
- Search parameters for this deployment: Zielstadt `Weinfelden`, Radius `15` km, Preislimit `CHF 650`, Zimmer-Minimum `keine`, Empfänger `icurafu333@gmail.com` (all live in `config.yaml`, not hardcoded in source).
- Commit after every task following the Step "Commit" pattern below — small, reviewable commits.

---

### Task 1: Project scaffolding — models, base interface, config, dependencies

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.yaml`
- Create: `src/__init__.py`
- Create: `src/models.py`
- Create: `src/scrapers/__init__.py`
- Create: `src/scrapers/base.py`
- Test: `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Listing` dataclass (`id: str, titel: str, preis: float, ort: str, zimmer: Optional[float], url: str, quelle: str`) in `src/models.py`, imported by every later task.
- Produces: `SearchConfig` dataclass (`stadt: str, radius_km: float, preis_max: float, zimmer_min: Optional[float], rate_limit_sekunden: float = 2.0`) and `ScraperError(Exception)` in `src/scrapers/base.py`, imported by every scraper and `main.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from src.models import Listing
from src.scrapers.base import ScraperError, SearchConfig


def test_listing_holds_all_fields():
    listing = Listing(
        id="flatfox:123",
        titel="3.5 Zimmer Wohnung",
        preis=650.0,
        ort="Weinfelden",
        zimmer=3.5,
        url="https://flatfox.ch/en/flat/example/123/",
        quelle="flatfox",
    )
    assert listing.id == "flatfox:123"
    assert listing.preis == 650.0
    assert listing.quelle == "flatfox"


def test_search_config_defaults_rate_limit():
    config = SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None)
    assert config.rate_limit_sekunden == 2.0


def test_scraper_error_is_an_exception():
    assert issubclass(ScraperError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src'` (or `src.models`)

- [ ] **Step 3: Create scaffolding and minimal implementation**

`requirements.txt`:
```
httpx>=0.27
playwright>=1.45
PyYAML>=6.0
python-dotenv>=1.0
pytest>=8.0
pytest-mock>=3.14
```

`.env.example`:
```
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
RECIPIENT_EMAIL=you@gmail.com
```

`config.yaml`:
```yaml
suche:
  stadt: "Weinfelden"
  radius_km: 15
  preis_max: 650
  zimmer_min: null   # null = keine Mindestanforderung
email:
  empfaenger: "icurafu333@gmail.com"
  nur_bei_treffern: true   # false = auch Emails ohne neue Treffer verschicken
scraper:
  aktiviert: [flatfox]
  rate_limit_sekunden: 2
```

`src/__init__.py`: (empty file)

`src/models.py`:
```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    id: str
    titel: str
    preis: float
    ort: str
    zimmer: Optional[float]
    url: str
    quelle: str
```

`src/scrapers/__init__.py`: (empty file)

`src/scrapers/base.py`:
```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchConfig:
    stadt: str
    radius_km: float
    preis_max: float
    zimmer_min: Optional[float]
    rate_limit_sekunden: float = 2.0


class ScraperError(Exception):
    """Raised by a scraper when it fails; caught per-scraper in main.py so one
    broken portal never stops the others."""
```

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example config.yaml src/__init__.py src/models.py \
  src/scrapers/__init__.py src/scrapers/base.py tests/__init__.py tests/test_models.py
git commit -m "Add project scaffolding: Listing/SearchConfig models, config.yaml, deps"
```

---

### Task 2: Dedupe store (`seen_listings.db`)

**Files:**
- Create: `src/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Consumes: `Listing` from `src/models.py` (Task 1).
- Produces: `init_db(path: str) -> sqlite3.Connection`, `filter_new(conn, listings: list[Listing]) -> list[Listing]`, `mark_seen(conn, listings: list[Listing]) -> None` — all consumed by `main.py` in Task 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedupe.py
from src.dedupe import filter_new, init_db, mark_seen
from src.models import Listing


def _listing(id_):
    return Listing(id=id_, titel="Test", preis=650.0, ort="Weinfelden", zimmer=None,
                    url="https://example.com", quelle="flatfox")


def test_filter_new_returns_all_on_empty_db():
    conn = init_db(":memory:")
    listings = [_listing("flatfox:1"), _listing("flatfox:2")]
    assert filter_new(conn, listings) == listings


def test_filter_new_excludes_already_seen():
    conn = init_db(":memory:")
    a, b = _listing("flatfox:1"), _listing("flatfox:2")
    mark_seen(conn, [a])
    assert filter_new(conn, [a, b]) == [b]


def test_mark_seen_is_idempotent():
    conn = init_db(":memory:")
    a = _listing("flatfox:1")
    mark_seen(conn, [a])
    mark_seen(conn, [a])
    count = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
    assert count == 1


def test_filter_new_handles_empty_input():
    conn = init_db(":memory:")
    assert filter_new(conn, []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dedupe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.dedupe'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/dedupe.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dedupe.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dedupe.py tests/test_dedupe.py
git commit -m "Add SQLite dedupe store for seen listings"
```

---

### Task 3: Geocoding — Nominatim client, cache, Haversine, bounding box

**Files:**
- Create: `src/geocode.py`
- Test: `tests/test_geocode.py`

**Rationale for hand-rolled Nominatim client instead of `geopy`:** the design spec named `geopy`, but the only thing needed is a single cached HTTP GET plus a Haversine formula — pulling in `geopy` (and its `RateLimiter`/`Nominatim` wrapper) adds a dependency for ~15 lines of logic already covered by `httpx` (already a dependency for Flatfox) and stdlib `math`. Dropped per YAGNI; revisit if geopy's geocoder fallback chain is ever needed.

**Interfaces:**
- Produces: `init_geocode_cache(conn) -> None`, `geocode(conn, query: str) -> Optional[tuple[float, float]]`, `haversine_km(lat1, lon1, lat2, lon2) -> float`, `bbox_around(lat, lon, radius_km) -> dict` (keys `north/south/east/west`), `filter_by_radius(conn, listings, center: tuple[float, float], radius_km: float) -> list[Listing]`.
- Consumed by: `src/scrapers/flatfox.py`, `src/scrapers/comparis.py` (Tasks 4, 9) and `src/main.py` (Task 6).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geocode.py
import sqlite3

from src.geocode import bbox_around, filter_by_radius, geocode, haversine_km, init_geocode_cache
from src.models import Listing


def _conn():
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    return conn


def test_geocode_returns_cached_value_without_network(mocker):
    conn = _conn()
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.commit()
    mock_get = mocker.patch("src.geocode.httpx.get")

    result = geocode(conn, "Weinfelden")

    assert result == (47.5669187, 9.1097539)
    mock_get.assert_not_called()


def test_geocode_calls_nominatim_and_caches_result(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = [{"lat": "47.5669187", "lon": "9.1097539"}]
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")

    result = geocode(conn, "Weinfelden")

    assert result == (47.5669187, 9.1097539)
    cached = conn.execute("SELECT lat, lon FROM geocode_cache WHERE query = 'Weinfelden'").fetchone()
    assert cached == (47.5669187, 9.1097539)


def test_geocode_returns_none_when_nominatim_finds_nothing(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = []
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")

    assert geocode(conn, "Nirgendwo") is None


def test_haversine_zurich_to_bern_is_about_95km():
    distance = haversine_km(47.3769, 8.5417, 46.9480, 7.4474)
    assert 90 < distance < 100


def test_bbox_around_grows_with_radius():
    small = bbox_around(47.5669187, 9.1097539, 5)
    large = bbox_around(47.5669187, 9.1097539, 15)
    assert large["north"] - large["south"] > small["north"] - small["south"]
    assert small["south"] < 47.5669187 < small["north"]


def test_filter_by_radius_keeps_only_nearby_listings():
    conn = _conn()
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Zürich', 47.3769, 8.5417)")
    conn.commit()
    near = Listing(id="a", titel="near", preis=650, ort="Weinfelden", zimmer=None, url="https://x", quelle="flatfox")
    far = Listing(id="b", titel="far", preis=650, ort="Zürich", zimmer=None, url="https://y", quelle="flatfox")

    kept = filter_by_radius(conn, [near, far], center=(47.5669187, 9.1097539), radius_km=15)

    assert kept == [near]


def test_filter_by_radius_skips_listings_that_cannot_be_geocoded(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = []
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")
    unresolvable = Listing(id="c", titel="?", preis=650, ort="???", zimmer=None, url="https://z", quelle="flatfox")

    assert filter_by_radius(conn, [unresolvable], center=(47.5669187, 9.1097539), radius_km=15) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_geocode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.geocode'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/geocode.py
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

    response = httpx.get(
        NOMINATIM_URL,
        params={"q": f"{query}, Switzerland", "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_geocode.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/geocode.py tests/test_geocode.py
git commit -m "Add Nominatim geocoding with SQLite cache, Haversine filter, bbox helper"
```

---

### Task 4: Flatfox scraper (JSON API, first live source)

**Files:**
- Create: `src/scrapers/flatfox.py`
- Create: `tests/fixtures/flatfox_pins.json`
- Create: `tests/fixtures/flatfox_listings.json`
- Test: `tests/test_flatfox.py`

**Grounding:** verified live on 2026-08-11 — `GET https://flatfox.ch/api/v1/pin/?east=&north=&south=&west=&offer_type=RENT&max_count=` returns bounding-box pins (`pk`, `latitude`, `longitude`, `price_display`); `GET https://flatfox.ch/api/v1/public-listing/?pk=<id>&pk=<id>&limit=N` returns full listing objects (confirmed real fields: `pk`, `url` (relative), `price_display`, `number_of_rooms` (string, e.g. `"4.0"`), `city`, `short_title`, `public_title`). No anti-bot on this API; `robots.txt` allows it.

**Interfaces:**
- Consumes: `SearchConfig`, `ScraperError` (Task 1); `Listing` (Task 1); `geo.geocode`, `geo.bbox_around` (Task 3).
- Produces: `scrape(config: SearchConfig, geocode_conn) -> list[Listing]`, registered in `main.py`'s `SCRAPERS` dict as `"flatfox"` (Task 6).

- [ ] **Step 1: Create fixtures from real captured data**

`tests/fixtures/flatfox_pins.json`:
```json
[
  {"pk": 86263289, "smg_id": "4003375644", "latitude": 47.4850196, "longitude": 8.9902972, "price_display": 3600, "price_display_type": "TOTAL", "price_unit": "monthly", "offer_type": "RENT"},
  {"pk": 86263510, "smg_id": "4003375837", "latitude": 47.5701, "longitude": 9.1123, "price_display": 620, "price_display_type": "TOTAL", "price_unit": "monthly", "offer_type": "RENT"}
]
```

`tests/fixtures/flatfox_listings.json`:
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "pk": 86263289,
      "url": "/en/flat/mezikonerstrassw-7a-9542-munchwilen-tg/86263289/",
      "price_display": 2430,
      "number_of_rooms": "4.0",
      "city": "Münchwilen TG",
      "short_title": "4 rooms apartment",
      "public_title": "Mezikonerstrassw 7a, 9542 Münchwilen TG - CHF 2’430"
    },
    {
      "pk": 86263510,
      "url": "/en/flat/beispielstrasse-1-8570-weinfelden/86263510/",
      "price_display": 620,
      "number_of_rooms": "1.0",
      "city": "Weinfelden",
      "short_title": "1 room apartment",
      "public_title": "Beispielstrasse 1, 8570 Weinfelden - CHF 620"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_flatfox.py
import json
import sqlite3
from pathlib import Path

import pytest

from src.geocode import init_geocode_cache
from src.scrapers import flatfox
from src.scrapers.base import ScraperError, SearchConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _config():
    return SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None)


def _conn_with_weinfelden_cached():
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.commit()
    return conn


def test_to_listing_maps_real_flatfox_fields():
    raw = json.loads((FIXTURES / "flatfox_listings.json").read_text())["results"][0]

    listing = flatfox._to_listing(raw)

    assert listing.id == "flatfox:86263289"
    assert listing.preis == 2430.0
    assert listing.zimmer == 4.0
    assert listing.ort == "Münchwilen TG"
    assert listing.url == "https://flatfox.ch/en/flat/mezikonerstrassw-7a-9542-munchwilen-tg/86263289/"
    assert listing.quelle == "flatfox"


def test_to_listing_handles_missing_room_count():
    raw = {"pk": 1, "url": "/x/1/", "price_display": 650, "number_of_rooms": None,
           "city": "Weinfelden", "short_title": "Studio", "public_title": "Studio"}

    listing = flatfox._to_listing(raw)

    assert listing.zimmer is None


def test_scrape_returns_listings_from_mocked_api(mocker):
    pins = json.loads((FIXTURES / "flatfox_pins.json").read_text())
    listings_response = json.loads((FIXTURES / "flatfox_listings.json").read_text())

    mock_pins_response = mocker.Mock()
    mock_pins_response.json.return_value = pins
    mock_pins_response.raise_for_status.return_value = None

    mock_listings_response = mocker.Mock()
    mock_listings_response.json.return_value = listings_response
    mock_listings_response.raise_for_status.return_value = None

    mock_client = mocker.MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [mock_pins_response, mock_listings_response]
    mocker.patch("src.scrapers.flatfox.httpx.Client", return_value=mock_client)

    result = flatfox.scrape(_config(), _conn_with_weinfelden_cached())

    assert len(result) == 2
    assert all(listing.quelle == "flatfox" for listing in result)


def test_scrape_raises_scraper_error_when_city_not_geocodable(mocker):
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    empty_response = mocker.Mock()
    empty_response.json.return_value = []
    empty_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=empty_response)
    mocker.patch("src.geocode.time.sleep")

    with pytest.raises(ScraperError):
        flatfox.scrape(_config(), conn)


def test_scrape_raises_scraper_error_on_http_failure(mocker):
    import httpx as httpx_module

    mock_client = mocker.MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = httpx_module.HTTPError("boom")
    mocker.patch("src.scrapers.flatfox.httpx.Client", return_value=mock_client)

    with pytest.raises(ScraperError):
        flatfox.scrape(_config(), _conn_with_weinfelden_cached())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_flatfox.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.scrapers.flatfox'`

- [ ] **Step 4: Write minimal implementation**

```python
# src/scrapers/flatfox.py
import httpx

from src import geocode as geo
from src.models import Listing
from src.scrapers.base import ScraperError, SearchConfig

BASE_URL = "https://flatfox.ch/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _fetch_pins(client: httpx.Client, bbox: dict) -> list[dict]:
    params = {**bbox, "offer_type": "RENT", "max_count": 500}
    response = client.get(f"{BASE_URL}/pin/", params=params)
    response.raise_for_status()
    return response.json()


def _fetch_listing_details(client: httpx.Client, pks: list[int]) -> list[dict]:
    if not pks:
        return []
    params = [("pk", pk) for pk in pks] + [("limit", len(pks))]
    response = client.get(f"{BASE_URL}/public-listing/", params=params)
    response.raise_for_status()
    return response.json()["results"]


def _to_listing(raw: dict) -> Listing:
    rooms = raw.get("number_of_rooms")
    return Listing(
        id=f"flatfox:{raw['pk']}",
        titel=raw.get("short_title") or raw.get("public_title", ""),
        preis=float(raw["price_display"]),
        ort=raw.get("city", ""),
        zimmer=float(rooms) if rooms not in (None, "") else None,
        url=f"https://flatfox.ch{raw['url']}",
        quelle="flatfox",
    )


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    center = geo.geocode(geocode_conn, config.stadt)
    if center is None:
        raise ScraperError(f"flatfox: Zielstadt '{config.stadt}' konnte nicht geokodiert werden")
    bbox = geo.bbox_around(center[0], center[1], config.radius_km)

    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=15) as client:
            pins = _fetch_pins(client, bbox)
            pks = [pin["pk"] for pin in pins]
            raw_listings = _fetch_listing_details(client, pks)
    except httpx.HTTPError as exc:
        raise ScraperError(f"flatfox: Anfrage fehlgeschlagen — {exc}") from exc

    return [_to_listing(raw) for raw in raw_listings]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_flatfox.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/scrapers/flatfox.py tests/test_flatfox.py tests/fixtures/flatfox_pins.json tests/fixtures/flatfox_listings.json
git commit -m "Add Flatfox scraper using its public JSON API"
```

---

### Task 5: Notifier — HTML email builder + SMTP send

**Files:**
- Create: `src/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `Listing` (Task 1).
- Produces: `EmailConfig` dataclass, `build_subject(new_count: int) -> str`, `build_html(listings: list[Listing], errors: list[str]) -> str`, `send_email(config: EmailConfig, subject: str, html_body: str) -> None` — all consumed by `main.py` (Task 6).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notifier.py
from unittest.mock import MagicMock

from src.models import Listing
from src.notifier import EmailConfig, build_html, build_subject, send_email


def _listing(preis=650.0, ort="Weinfelden", quelle="flatfox"):
    return Listing(id="flatfox:1", titel="Test", preis=preis, ort=ort, zimmer=2.5,
                   url="https://example.com/1", quelle=quelle)


def test_build_subject_with_no_hits():
    assert build_subject(0) == "Immo-Scraper: keine neuen Treffer"


def test_build_subject_with_hits():
    assert build_subject(3) == "Immo-Scraper: 3 neue Treffer"


def test_build_html_includes_listing_row():
    html = build_html([_listing()], [])
    assert "CHF 650" in html
    assert "Weinfelden" in html
    assert "flatfox" in html


def test_build_html_shows_empty_state():
    html = build_html([], [])
    assert "Keine neuen Treffer" in html


def test_build_html_includes_error_section():
    html = build_html([], ["homegate: Layout geändert?"])
    assert "Fehler" in html
    assert "homegate: Layout geändert?" in html


def test_send_email_logs_in_and_sends(mocker):
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    mocker.patch("src.notifier.smtplib.SMTP_SSL", return_value=mock_smtp)

    config = EmailConfig(gmail_address="a@gmail.com", gmail_app_password="secret", recipient="b@gmail.com")
    send_email(config, "Subject", "<p>Body</p>")

    mock_smtp.login.assert_called_once_with("a@gmail.com", "secret")
    assert mock_smtp.sendmail.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.notifier'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/notifier.py
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.models import Listing


@dataclass
class EmailConfig:
    gmail_address: str
    gmail_app_password: str
    recipient: str


def build_subject(new_count: int) -> str:
    if new_count == 0:
        return "Immo-Scraper: keine neuen Treffer"
    return f"Immo-Scraper: {new_count} neue Treffer"


def build_html(listings: list[Listing], errors: list[str]) -> str:
    if listings:
        rows = "\n".join(
            f"<tr><td>CHF {listing.preis:.0f}</td><td>{listing.ort}</td>"
            f"<td>{listing.zimmer if listing.zimmer is not None else '-'}</td>"
            f"<td><a href=\"{listing.url}\">Inserat</a></td><td>{listing.quelle}</td></tr>"
            for listing in listings
        )
        table = (
            "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
            "<tr><th>Preis</th><th>Ort</th><th>Zimmer</th><th>Link</th><th>Quelle</th></tr>"
            f"{rows}</table>"
        )
    else:
        table = "<p>Keine neuen Treffer.</p>"

    error_section = ""
    if errors:
        items = "".join(f"<li>{error}</li>" for error in errors)
        error_section = f"<h3>⚠️ Fehler bei folgenden Scrapern</h3><ul>{items}</ul>"

    return f"<h2>{len(listings)} neue Treffer</h2>{table}{error_section}"


def send_email(config: EmailConfig, subject: str, html_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.gmail_address
    message["To"] = config.recipient
    message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config.gmail_address, config.gmail_app_password)
        server.sendmail(config.gmail_address, [config.recipient], message.as_string())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "Add HTML email builder and Gmail SMTP sender"
```

---

### Task 6: Orchestrator (`main.py`) — Phase 1 vertical slice complete

**Files:**
- Create: `src/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `dedupe.init_db/filter_new/mark_seen` (Task 2), `geocode.init_geocode_cache/geocode/filter_by_radius` (Task 3), `flatfox.scrape` (Task 4), `notifier.EmailConfig/build_subject/build_html/send_email` (Task 5), `SearchConfig/ScraperError` (Task 1).
- Produces: `SCRAPERS: dict[str, Callable]`, `load_config(path) -> tuple[SearchConfig, dict]`, `run(config_path=..., db_path=...) -> None`. Later tasks (7, 8, 9) extend `SCRAPERS` and `config.yaml`'s `scraper.aktiviert` list — they do not change `run()`'s logic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
import sqlite3
from pathlib import Path

import yaml

from src.geocode import init_geocode_cache
from src.models import Listing
from src.scrapers.base import ScraperError


def _write_config(tmp_path: Path) -> Path:
    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near", "fake_far", "fake_broken"], "rate_limit_sekunden": 0},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def _seed_geocode_cache(db_path: Path, *, include_zurich: bool) -> None:
    conn = sqlite3.connect(str(db_path))
    init_geocode_cache(conn)
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    if include_zurich:
        conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Zürich', 47.3769, 8.5417)")
    conn.commit()
    conn.close()


def test_run_sends_email_with_only_new_nearby_affordable_listings(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    far = Listing(id="fake:far", titel="Far", preis=600, ort="Zürich", zimmer=None,
                   url="https://x/2", quelle="fake_far")

    def broken_scrape(config, conn):
        raise ScraperError("fake_broken: Layout geändert?")

    mocker.patch("src.main.SCRAPERS", {
        "fake_near": lambda config, conn: [near],
        "fake_far": lambda config, conn: [far],
        "fake_broken": broken_scrape,
    })
    sent = {}
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent.update(subject=subject, html=html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config_path = _write_config(tmp_path)
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=True)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert "Near" in sent["html"]
    assert "Zürich" not in sent["html"]
    assert "fake_broken: Layout geändert?" in sent["html"]


def test_run_does_not_resend_already_seen_listing(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: [near]})
    sent_calls = []
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent_calls.append(html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })
    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)
    main.run(config_path=config_path, db_path=db_path)

    assert len(sent_calls) == 1  # second run found nothing new, nur_bei_treffern=True suppresses the email


def test_run_skips_email_when_no_hits_and_no_errors(tmp_path, mocker):
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: []})
    send_mock = mocker.patch("src.main.send_email")
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })
    config_path = _write_config(tmp_path)
    config_path.write_text(yaml.safe_dump({
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    send_mock.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.main'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/main.py
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import dedupe, geocode as geo
from src.notifier import EmailConfig, build_html, build_subject, send_email
from src.scrapers import flatfox
from src.scrapers.base import ScraperError, SearchConfig

SCRAPERS = {
    "flatfox": flatfox.scrape,
}

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
DEFAULT_DB_PATH = ROOT / "seen_listings.db"


def load_config(path: Path) -> tuple[SearchConfig, dict]:
    raw = yaml.safe_load(path.read_text())
    search_config = SearchConfig(
        stadt=raw["suche"]["stadt"],
        radius_km=float(raw["suche"]["radius_km"]),
        preis_max=float(raw["suche"]["preis_max"]),
        zimmer_min=raw["suche"]["zimmer_min"],
        rate_limit_sekunden=float(raw["scraper"]["rate_limit_sekunden"]),
    )
    return search_config, raw


def run(config_path: Path = DEFAULT_CONFIG_PATH, db_path: Path = DEFAULT_DB_PATH) -> None:
    load_dotenv()
    search_config, raw_config = load_config(config_path)

    conn = dedupe.init_db(str(db_path))
    geo.init_geocode_cache(conn)

    center = geo.geocode(conn, search_config.stadt)
    if center is None:
        raise SystemExit(f"Zielstadt '{search_config.stadt}' konnte nicht geokodiert werden.")

    all_listings = []
    errors = []
    for name in raw_config["scraper"]["aktiviert"]:
        scrape_fn = SCRAPERS[name]
        try:
            all_listings.extend(scrape_fn(search_config, conn))
        except ScraperError as exc:
            errors.append(str(exc))

    nearby = geo.filter_by_radius(conn, all_listings, center, search_config.radius_km)
    filtered = [
        listing for listing in nearby
        if listing.preis <= search_config.preis_max
        and (
            search_config.zimmer_min is None
            or (listing.zimmer is not None and listing.zimmer >= search_config.zimmer_min)
        )
    ]

    new_listings = dedupe.filter_new(conn, filtered)
    new_listings.sort(key=lambda listing: listing.preis)
    dedupe.mark_seen(conn, new_listings)

    should_send = new_listings or errors or not raw_config["email"]["nur_bei_treffern"]
    if should_send:
        email_config = EmailConfig(
            gmail_address=os.environ["GMAIL_ADDRESS"],
            gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
            recipient=raw_config["email"]["empfaenger"],
        )
        send_email(email_config, build_subject(len(new_listings)), build_html(new_listings, errors))

    conn.close()


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite so far**

Run: `pytest -v`
Expected: all tests from Tasks 1–6 pass (around 25 tests)

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "Wire up main.py orchestrator — Phase 1 vertical slice (Flatfox) complete"
```

---

### Task 7: Homegate scraper (Playwright, DataDome-protected) — shared platform module

**Files:**
- Create: `src/scrapers/homegate_platform.py`
- Create: `src/scrapers/homegate.py`
- Test: `tests/test_homegate_platform.py`
- Test: `tests/test_homegate.py`
- Modify: `src/main.py:9-11` (SCRAPERS dict) and import line
- Modify: `config.yaml:11` (`scraper.aktiviert`)

**Grounding:** verified live on 2026-08-11 via real-browser DevTools inspection. `robots.txt` disallows `/*?*an=` generically but explicitly allows `/mieten/immobilien/*/trefferliste?an=G` — the `an=G` query param is required to stay compliant. Plain curl gets HTTP 403 (DataDome); a real, non-flagged-headless Chromium passes. Confirmed stable selectors: result container `[data-test="result-list"]`, each card `[data-test="result-list-item"]`, listing link matches `/mieten/<numeric-id>`, price class prefix `HgListingCard_mainTitle_`/`HgListingCard_price_`, address class prefix `HgListingCard_address_`, secondary line (rooms/size) class prefix `HgListingCard_secondaryTitle_` (e.g. `"3.5 Zimmer, 80 m²"`). Class names carry a build-hash suffix — match with `[class*="..."]`, never the full class string.

**Interfaces:**
- Consumes: `Listing`, `ScraperError` (Task 1).
- Produces: `scrape_platform(base_url: str, quelle: str, stadt: str, rate_limit_sekunden: float) -> list[Listing]` in `homegate_platform.py`, reused by `immoscout24.py` in Task 8. `homegate.py` exposes `scrape(config: SearchConfig, geocode_conn) -> list[Listing]`, registered as `"homegate"` in `main.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_homegate_platform.py
from unittest.mock import MagicMock

from src.scrapers.homegate_platform import _parse_card, _parse_price, _parse_rooms, _slugify_city


def test_slugify_city_lowercases_and_hyphenates():
    assert _slugify_city("Weinfelden") == "weinfelden"
    assert _slugify_city("St. Gallen") == "st.-gallen"


def test_parse_price_extracts_digits():
    assert _parse_price("CHF 2'900.–") == 2900.0


def test_parse_price_returns_none_for_empty_text():
    assert _parse_price("") is None


def test_parse_rooms_extracts_room_count():
    assert _parse_rooms("3.5 Zimmer, 80 m²") == 3.5


def test_parse_rooms_returns_none_when_absent():
    assert _parse_rooms("80 m²") is None


def _element(text):
    element = MagicMock()
    element.inner_text.return_value = text
    return element


def test_parse_card_builds_listing_from_dom_elements():
    card = MagicMock()

    def query_selector(selector):
        if "href" in selector:
            link = MagicMock()
            link.get_attribute.return_value = "/mieten/4003365027"
            return link
        if "mainTitle" in selector or "price" in selector:
            return _element("CHF 2'900.–")
        if "address" in selector:
            return _element("Gaswerkstrasse 7, 8570 Weinfelden")
        if "secondaryTitle" in selector:
            return _element("3.5 Zimmer, 80 m²")
        return None

    card.query_selector.side_effect = query_selector

    listing = _parse_card(card, "https://www.homegate.ch", "homegate")

    assert listing.id == "homegate:4003365027"
    assert listing.preis == 2900.0
    assert listing.ort == "Gaswerkstrasse 7, 8570 Weinfelden"
    assert listing.zimmer == 3.5
    assert listing.url == "https://www.homegate.ch/mieten/4003365027"
    assert listing.quelle == "homegate"


def test_parse_card_returns_none_without_link():
    card = MagicMock()
    card.query_selector.return_value = None
    assert _parse_card(card, "https://www.homegate.ch", "homegate") is None
```

```python
# tests/test_homegate.py
from src.scrapers.base import SearchConfig


def test_scrape_calls_shared_platform_with_homegate_domain(mocker):
    mock_scrape_platform = mocker.patch("src.scrapers.homegate.scrape_platform", return_value=[])
    from src.scrapers.homegate import scrape

    config = SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None, rate_limit_sekunden=2)
    scrape(config, geocode_conn=None)

    mock_scrape_platform.assert_called_once_with("https://www.homegate.ch", "homegate", "Weinfelden", 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_homegate_platform.py tests/test_homegate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.scrapers.homegate_platform'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/scrapers/homegate_platform.py
import re
import time
from typing import Optional

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from src.models import Listing
from src.scrapers.base import ScraperError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _slugify_city(city: str) -> str:
    return city.strip().lower().replace(" ", "-")


def _parse_price(text: str) -> Optional[float]:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else None


def _parse_rooms(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*Zimmer", text or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _parse_card(card, base_url: str, quelle: str) -> Optional[Listing]:
    link = card.query_selector('a[href*="/mieten/"]')
    if link is None:
        return None
    href = link.get_attribute("href") or ""
    id_match = re.search(r"/mieten/(\d+)", href)
    if id_match is None:
        return None
    listing_id = id_match.group(1)
    url = href if href.startswith("http") else f"{base_url}{href}"

    price_el = card.query_selector('[class*="HgListingCard_mainTitle"], [class*="HgListingCard_price"]')
    address_el = card.query_selector('[class*="HgListingCard_address"]')
    secondary_el = card.query_selector('[class*="HgListingCard_secondaryTitle"]')
    secondary_text = secondary_el.inner_text() if secondary_el else ""

    return Listing(
        id=f"{quelle}:{listing_id}",
        titel=secondary_text.strip() or "Wohnung",
        preis=_parse_price(price_el.inner_text() if price_el else "") or 0.0,
        ort=(address_el.inner_text() if address_el else "").strip(),
        zimmer=_parse_rooms(secondary_text),
        url=url,
        quelle=quelle,
    )


def scrape_platform(base_url: str, quelle: str, stadt: str, rate_limit_sekunden: float) -> list[Listing]:
    city_slug = _slugify_city(stadt)
    url = f"{base_url}/mieten/immobilien/ort-{city_slug}/trefferliste?an=G"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900})
            page.goto(url, timeout=30000)
            page.wait_for_selector('[data-test="result-list"]', timeout=15000)
            cards = page.query_selector_all('[data-test="result-list-item"]')
            listings = [_parse_card(card, base_url, quelle) for card in cards]
            browser.close()
    except PlaywrightError as exc:
        raise ScraperError(f"{quelle}: Ergebnisliste nicht ladbar (Layout geändert oder blockiert?) — {exc}") from exc

    time.sleep(rate_limit_sekunden)
    return [listing for listing in listings if listing is not None]
```

```python
# src/scrapers/homegate.py
from src.models import Listing
from src.scrapers.base import SearchConfig
from src.scrapers.homegate_platform import scrape_platform

BASE_URL = "https://www.homegate.ch"


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    return scrape_platform(BASE_URL, "homegate", config.stadt, config.rate_limit_sekunden)
```

Then update `src/main.py`'s import and `SCRAPERS` dict:

```python
# src/main.py — replace the existing import + SCRAPERS block
from src.scrapers import flatfox, homegate

SCRAPERS = {
    "flatfox": flatfox.scrape,
    "homegate": homegate.scrape,
}
```

And `config.yaml`:
```yaml
scraper:
  aktiviert: [flatfox, homegate]
  rate_limit_sekunden: 2
```

- [ ] **Step 4: Install Playwright's browser binary (one-time, local dev)**

Run: `playwright install --with-deps chromium`
Expected: Chromium downloads successfully (no test dependency on this — it's required to actually run `homegate.scrape`, not to run the unit tests, which never launch a browser).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_homegate_platform.py tests/test_homegate.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: all prior tests plus these 8 pass

- [ ] **Step 7: Commit**

```bash
git add src/scrapers/homegate_platform.py src/scrapers/homegate.py \
  tests/test_homegate_platform.py tests/test_homegate.py src/main.py config.yaml
git commit -m "Add Homegate scraper via Playwright, wire into main.py"
```

---

### Task 8: ImmoScout24 scraper (reuses Homegate's platform module)

**Files:**
- Create: `src/scrapers/immoscout24.py`
- Test: `tests/test_immoscout24.py`
- Modify: `src/main.py` (SCRAPERS dict + import)
- Modify: `config.yaml` (`scraper.aktiviert`)

**Grounding:** verified live on 2026-08-11 — immoscout24.ch runs on the identical Swiss Marketplace Group platform as homegate.ch (identical `data-test` attributes and CSS class hashes confirmed by cross-comparing a live search on both sites). `robots.txt` disallows `/*?*an=` but allows `/de/immobilien/mieten/*?an=G`.

**Interfaces:**
- Consumes: `scrape_platform` (Task 7), `SearchConfig` (Task 1).
- Produces: `scrape(config: SearchConfig, geocode_conn) -> list[Listing]`, registered as `"immoscout24"` in `main.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_immoscout24.py
from src.scrapers.base import SearchConfig


def test_scrape_calls_shared_platform_with_immoscout24_domain(mocker):
    mock_scrape_platform = mocker.patch("src.scrapers.immoscout24.scrape_platform", return_value=[])
    from src.scrapers.immoscout24 import scrape

    config = SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None, rate_limit_sekunden=2)
    scrape(config, geocode_conn=None)

    mock_scrape_platform.assert_called_once_with("https://www.immoscout24.ch", "immoscout24", "Weinfelden", 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_immoscout24.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.scrapers.immoscout24'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/scrapers/immoscout24.py
from src.models import Listing
from src.scrapers.base import SearchConfig
from src.scrapers.homegate_platform import scrape_platform

BASE_URL = "https://www.immoscout24.ch"


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    return scrape_platform(BASE_URL, "immoscout24", config.stadt, config.rate_limit_sekunden)
```

Update `src/main.py`:
```python
from src.scrapers import flatfox, homegate, immoscout24

SCRAPERS = {
    "flatfox": flatfox.scrape,
    "homegate": homegate.scrape,
    "immoscout24": immoscout24.scrape,
}
```

Update `config.yaml`:
```yaml
scraper:
  aktiviert: [flatfox, homegate, immoscout24]
  rate_limit_sekunden: 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_immoscout24.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/scrapers/immoscout24.py tests/test_immoscout24.py src/main.py config.yaml
git commit -m "Add ImmoScout24 scraper, reusing the shared SMG platform parser"
```

---

### Task 9: Comparis scraper (Playwright, own DOM — most speculative of the four)

**Files:**
- Create: `src/scrapers/comparis.py`
- Test: `tests/test_comparis.py`
- Modify: `src/main.py` (SCRAPERS dict + import)
- Modify: `config.yaml` (`scraper.aktiviert`)

**Grounding:** verified live on 2026-08-11. `robots.txt` disallows `/immobilien/api/`, `/immobilien/searchservice/`, `/immobilien/details/`, `/immobilien/dataProvider/` but **not** `/immobilien/result/list` — the scraper must use that HTML route, never the JSON twin at `/immobilien/api/...`. Real captured search URL: `GET https://www.comparis.ch/immobilien/result/list?requestobject=<url-encoded JSON>` with a confirmed-real partial schema (`DealType:10` for rent, `LocationSearchString`, `Sort:11`, `PriceTo`, `LowerLeft/UpperRightLatitude/Longitude` for a bounding box, `SwapProperty:1`). The full schema has 30+ fields (PascalCase, .NET-style API); this plan intentionally sends only the fields it knows and needs — .NET model binding defaults missing JSON properties rather than rejecting the request. Comparis uses Emotion CSS-in-JS with build-hashed class names (**not** durable selectors) but a stable URL pattern for listing links: `/immobilien/marktplatz/details/show/<numeric-id>`. DataDome-protected like Homegate/ImmoScout24 — same real-Chromium approach required.

**Interfaces:**
- Consumes: `geo.geocode`, `geo.bbox_around` (Task 3), `SearchConfig`, `ScraperError`, `Listing` (Task 1).
- Produces: `scrape(config: SearchConfig, geocode_conn) -> list[Listing]`, registered as `"comparis"` in `main.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_comparis.py
import json
import urllib.parse
from unittest.mock import MagicMock

from src.scrapers.comparis import build_request_object, build_search_url, _parse_link, _parse_price, _parse_rooms


def test_build_request_object_sets_rent_deal_type_and_price_ceiling():
    bbox = {"north": 47.7, "south": 47.4, "east": 9.3, "west": 8.9}

    request_object = build_request_object("Weinfelden", 650, bbox)

    assert request_object["DealType"] == 10
    assert request_object["PriceTo"] == 650
    assert request_object["LocationSearchString"] == "Weinfelden"
    assert request_object["UpperRightLatitude"] == 47.7
    assert request_object["LowerLeftLongitude"] == 8.9


def test_build_search_url_embeds_encoded_request_object():
    request_object = {"DealType": 10, "LocationSearchString": "Weinfelden"}

    url = build_search_url(request_object)

    assert url.startswith("https://www.comparis.ch/immobilien/result/list?requestobject=")
    encoded = url.split("requestobject=")[1]
    assert json.loads(urllib.parse.unquote(encoded)) == request_object


def test_parse_price_handles_swiss_thousands_separator():
    assert _parse_price("CHF 2’430.– pro Monat") == 2430.0


def test_parse_price_returns_none_without_chf_amount():
    assert _parse_price("Details anzeigen") is None


def test_parse_rooms_extracts_room_count():
    assert _parse_rooms("4.5 Zimmer, 102 m²") == 4.5


def test_parse_link_builds_listing_from_container_text():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/marktplatz/details/show/37785684"
    container = MagicMock()
    container.inner_text.return_value = "Mezikonerstrasse 7a, 9542 Münchwilen TG\n4.5 Zimmer\nCHF 2’430.–"
    handle = MagicMock()
    handle.as_element.return_value = container
    link.evaluate_handle.return_value = handle

    listing = _parse_link(link)

    assert listing.id == "comparis:37785684"
    assert listing.preis == 2430.0
    assert listing.zimmer == 4.5
    assert listing.url == "https://www.comparis.ch/immobilien/marktplatz/details/show/37785684"
    assert listing.quelle == "comparis"


def test_parse_link_returns_none_for_non_listing_link():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/some-other-page"

    assert _parse_link(link) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_comparis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.scrapers.comparis'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/scrapers/comparis.py
import json
import re
import time
import urllib.parse
from typing import Optional

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from src import geocode as geo
from src.models import Listing
from src.scrapers.base import ScraperError, SearchConfig

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
BASE_URL = "https://www.comparis.ch"

PRICE_RE = re.compile(r"CHF\s*([\d'’]+)")
ROOMS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*Zimmer")
ID_RE = re.compile(r"/immobilien/marktplatz/details/show/(\d+)")


def build_request_object(stadt: str, preis_max: float, bbox: dict) -> dict:
    return {
        "DealType": 10,  # mieten (rent)
        "SiteId": 0,
        "RootPropertyTypes": [],
        "PropertyTypes": [],
        "RoomsFrom": None,
        "RoomsTo": None,
        "PriceFrom": None,
        "PriceTo": preis_max,
        "LocationSearchString": stadt,
        "LocationSearchDistrict": None,
        "LocationSearchCity": None,
        "Sort": 11,  # Preis aufsteigend
        "LowerLeftLatitude": bbox["south"],
        "LowerLeftLongitude": bbox["west"],
        "UpperRightLatitude": bbox["north"],
        "UpperRightLongitude": bbox["east"],
        "SwapProperty": 1,
    }


def build_search_url(request_object: dict) -> str:
    encoded = urllib.parse.quote(json.dumps(request_object))
    return f"{BASE_URL}/immobilien/result/list?requestobject={encoded}"


def _parse_price(text: str) -> Optional[float]:
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    return float(match.group(1).replace("'", "").replace("’", ""))


def _parse_rooms(text: str) -> Optional[float]:
    match = ROOMS_RE.search(text or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _parse_link(link) -> Optional[Listing]:
    href = link.get_attribute("href") or ""
    id_match = ID_RE.search(href)
    if id_match is None:
        return None

    container = link.evaluate_handle(
        "el => el.closest('article') || el.closest('li') || el.parentElement?.parentElement || el"
    ).as_element()
    text = container.inner_text() if container else (link.inner_text() or "")

    return Listing(
        id=f"comparis:{id_match.group(1)}",
        titel=text.splitlines()[0].strip() if text else "Wohnung",
        preis=_parse_price(text) or 0.0,
        ort=text,
        zimmer=_parse_rooms(text),
        url=href if href.startswith("http") else f"{BASE_URL}{href}",
        quelle="comparis",
    )


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    center = geo.geocode(geocode_conn, config.stadt)
    if center is None:
        raise ScraperError(f"comparis: Zielstadt '{config.stadt}' konnte nicht geokodiert werden")
    bbox = geo.bbox_around(center[0], center[1], config.radius_km)
    url = build_search_url(build_request_object(config.stadt, config.preis_max, bbox))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900})
            page.goto(url, timeout=30000)
            page.wait_for_selector('a[href*="/immobilien/marktplatz/details/show/"]', timeout=15000)
            links = page.query_selector_all('a[href*="/immobilien/marktplatz/details/show/"]')

            seen_hrefs = set()
            listings = []
            for link in links:
                href = link.get_attribute("href") or ""
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                listing = _parse_link(link)
                if listing is not None:
                    listings.append(listing)
            browser.close()
    except PlaywrightError as exc:
        raise ScraperError(f"comparis: Ergebnisliste nicht ladbar (Layout geändert oder blockiert?) — {exc}") from exc

    time.sleep(config.rate_limit_sekunden)
    return listings
```

Update `src/main.py`:
```python
from src.scrapers import comparis, flatfox, homegate, immoscout24

SCRAPERS = {
    "flatfox": flatfox.scrape,
    "homegate": homegate.scrape,
    "immoscout24": immoscout24.scrape,
    "comparis": comparis.scrape,
}
```

Update `config.yaml`:
```yaml
scraper:
  aktiviert: [flatfox, homegate, immoscout24, comparis]
  rate_limit_sekunden: 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_comparis.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Capture a live fixture and verify the card-boundary heuristic (manual, one-time)**

This is the task where "which DOM element wraps a listing card" is the least certain of the four scrapers — Comparis's build-hashed classes gave no durable container selector to lock onto ahead of time, only the confirmed anchor-link pattern. Verify `_parse_link`'s `evaluate_handle` ancestor-walk against the real page before trusting it in production:

```bash
python3 -c "
import sqlite3
from src import geocode as geo
from src.scrapers.comparis import build_request_object, build_search_url
from playwright.sync_api import sync_playwright

conn = sqlite3.connect(':memory:')
geo.init_geocode_cache(conn)
center = geo.geocode(conn, 'Weinfelden')
bbox = geo.bbox_around(center[0], center[1], 15)
url = build_search_url(build_request_object('Weinfelden', 650, bbox))
print(url)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(url, timeout=30000)
    page.wait_for_selector('a[href*=\"/immobilien/marktplatz/details/show/\"]', timeout=15000)
    open('tests/fixtures/comparis_live_capture.html', 'w').write(page.content())
    browser.close()
"
```

Open `tests/fixtures/comparis_live_capture.html`, find a real `<a href="/immobilien/marktplatz/details/show/...">`, and confirm walking up via `closest('article')` / `closest('li')` / two `parentElement`s lands on a container whose text includes both a `CHF ...` price and a `... Zimmer` room count. If it doesn't, adjust the `evaluate_handle` expression in `_parse_link` to match the real nesting, add a regression test in `tests/test_comparis.py` using the real text you found, and re-run `pytest tests/test_comparis.py -v`. Delete `tests/fixtures/comparis_live_capture.html` afterward (it's a scratch file, not a fixture) or add it to `.gitignore` if you want to keep it for future reference.

- [ ] **Step 6: Commit**

```bash
git add src/scrapers/comparis.py tests/test_comparis.py src/main.py config.yaml
git commit -m "Add Comparis scraper via Playwright, driven by its result/list search URL"
```

---

### Task 10: GitHub Actions cron workflow

**Files:**
- Create: `.github/workflows/search.yml`
- Test: `tests/test_workflow_yaml.py`

**Interfaces:**
- Consumes: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL` as GitHub Actions Secrets (configured by the user in repo Settings, not by this task).

**Design note:** the dedupe/geocode-cache SQLite file (`seen_listings.db`) must persist across daily runs. `actions/cache` only saves on a cache-key miss, which doesn't fit ever-growing state — instead the workflow commits the updated `seen_listings.db` back to the repo after each run (`permissions: contents: write` + the default `GITHUB_TOKEN`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_yaml.py
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "search.yml"


def test_workflow_file_is_valid_yaml():
    assert WORKFLOW_PATH.exists()
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert "jobs" in workflow


def test_workflow_runs_on_schedule_and_manual_dispatch():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    triggers = workflow.get(True, workflow.get("on"))  # PyYAML parses bare `on:` key as boolean True
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_workflow_installs_playwright_chromium_with_deps():
    text = WORKFLOW_PATH.read_text()
    assert "playwright install --with-deps chromium" in text


def test_workflow_uses_xvfb_to_run_the_scraper():
    text = WORKFLOW_PATH.read_text()
    assert "xvfb-run" in text
    assert "python -m src.main" in text


def test_workflow_declares_all_three_secrets():
    text = WORKFLOW_PATH.read_text()
    for secret in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"):
        assert f"secrets.{secret}" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_yaml.py -v`
Expected: FAIL — `assert WORKFLOW_PATH.exists()` fails, file doesn't exist yet

- [ ] **Step 3: Write the workflow**

```yaml
# .github/workflows/search.yml
name: Immo Search

on:
  schedule:
    # 05:00 UTC = 07:00 Europe/Zurich during CEST (summer). During CET (winter)
    # this lands at 06:00 local time — cron has no timezone support, so a ~1h
    # seasonal drift is accepted for a daily digest rather than adding
    # complexity to work around it.
    - cron: "0 5 * * *"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  search:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          playwright install --with-deps chromium

      - name: Run scraper
        env:
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
        run: xvfb-run --auto-servernum python -m src.main

      - name: Persist seen-listings database
        run: |
          git config user.name "immo-scraper-bot"
          git config user.email "actions@users.noreply.github.com"
          git add seen_listings.db
          git diff --staged --quiet || git commit -m "Update seen listings [skip ci]"
          git diff --staged --quiet || git push
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_yaml.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/search.yml tests/test_workflow_yaml.py
git commit -m "Add GitHub Actions daily cron workflow"
```

---

### Task 11: README

**Files:**
- Modify: `README.md`

**Interfaces:** none — documentation only, no code consumes this file.

- [ ] **Step 1: Write the README**

```markdown
# Immo-Scraper

Automatisierte tägliche Suche nach Mietwohnungen in der Schweiz über Flatfox,
Homegate, ImmoScout24 und Comparis. Filtert nach Preis und Umkreis der
Zielstadt, dedupliziert über Läufe hinweg und verschickt neue Treffer per
Email, sortiert nach Preis (aufsteigend).

> **wgzimmer.ch wird nicht automatisiert:** jede Suche dort ist per
> reCAPTCHA geschützt. Prüfe WG-Zimmer manuell unter
> [wgzimmer.ch](https://www.wgzimmer.ch/wgzimmer/search/mate.html).

## Setup (lokal)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env
```

Trage in `.env` deine Gmail-Adresse, dein Gmail-App-Passwort und die
Zieladresse ein (siehe unten, wie man ein App-Passwort erstellt).

Passe bei Bedarf `config.yaml` an (Stadt, Radius in km, Preislimit,
Mindest-Zimmerzahl) — keine Code-Kenntnisse nötig.

Lauf lokal starten:

```bash
python -m src.main
```

Tests laufen komplett offline (kein Netzwerk, kein Browserstart):

```bash
pytest -v
```

## Gmail App-Passwort erstellen

1. Zwei-Faktor-Authentifizierung für dein Google-Konto aktivieren (falls noch
   nicht geschehen): https://myaccount.google.com/security
2. App-Passwörter öffnen: https://myaccount.google.com/apppasswords
3. App "Mail" wählen, Passwort generieren, das 16-stellige Passwort in
   `GMAIL_APP_PASSWORD` eintragen (lokal in `.env`, im CI als GitHub Secret).

## GitHub Actions Secrets einrichten

Im Repo unter **Settings → Secrets and variables → Actions → New repository
secret** folgende drei Secrets anlegen:

- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`
- `RECIPIENT_EMAIL`

Der Workflow `.github/workflows/search.yml` läuft täglich um 07:00 Uhr
Europe/Zurich (Sommerzeit; im Winter ca. 06:00 Uhr lokal, da GitHub-Cron keine
Zeitzonen kennt). Zeit anpassen: den `cron`-Ausdruck in der Workflow-Datei
ändern (Format: UTC, `Minute Stunde * * *`).

Manuell auslösen: Tab **Actions** im Repo → Workflow **Immo Search** →
**Run workflow**.

## Architektur

Siehe [`docs/superpowers/specs/2026-08-11-immo-scraper-design.md`](docs/superpowers/specs/2026-08-11-immo-scraper-design.md)
für die vollständige Design-Doku (Datenfluss, Portal-Recherche, robots.txt-
Compliance je Portal).
```

- [ ] **Step 2: Verify the README covers every required topic**

Run: `grep -c -E "^## " README.md`
Expected: at least 5 (Setup, Gmail App-Passwort, GitHub Actions Secrets, Architektur, plus the wgzimmer.ch callout)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Write README: setup, Gmail app password, GitHub Actions secrets, wgzimmer.ch note"
```
