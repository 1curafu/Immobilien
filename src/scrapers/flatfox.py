from typing import Optional

import httpx

from src import geocode as geo
from src.models import Listing
from src.scrapers.base import ScraperError, SearchConfig

BASE_URL = "https://flatfox.ch/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
# A single public-listing/ request with ~500 pk= params produces a URL long
# enough that flatfox.ch's edge returns a 520 (confirmed live 2026-08-18: 450
# pks/~5.4KB URL succeeds, 500 pks/~6KB fails). 100 per chunk keeps a wide
# safety margin while still being few enough requests for a daily run.
CHUNK_SIZE = 100


def _fetch_pins(client: httpx.Client, bbox: dict) -> list[dict]:
    params = {**bbox, "offer_type": "RENT", "max_count": 500}
    response = client.get(f"{BASE_URL}/pin/", params=params)
    response.raise_for_status()
    return response.json()


def _fetch_listing_details(client: httpx.Client, pks: list[int]) -> list[dict]:
    results = []
    for i in range(0, len(pks), CHUNK_SIZE):
        chunk = pks[i:i + CHUNK_SIZE]
        params = [("pk", pk) for pk in chunk] + [("limit", len(chunk))]
        response = client.get(f"{BASE_URL}/public-listing/", params=params)
        response.raise_for_status()
        results.extend(response.json()["results"])
    return results


def _to_listing(raw: dict) -> Optional[Listing]:
    # price_display is sometimes present but null (e.g. "price on request"
    # listings) — confirmed live 2026-08-18. Skip that one listing rather
    # than let it abort the whole batch; same for any other missing/malformed
    # essential field (pk, url).
    price = raw.get("price_display")
    pk = raw.get("pk")
    url = raw.get("url")
    if price is None or pk is None or url is None:
        return None
    try:
        preis = float(price)
    except (TypeError, ValueError):
        return None

    rooms = raw.get("number_of_rooms")
    return Listing(
        id=f"flatfox:{pk}",
        titel=raw.get("short_title") or raw.get("public_title", ""),
        preis=preis,
        ort=raw.get("city", ""),
        zimmer=float(rooms) if rooms not in (None, "") else None,
        url=f"https://flatfox.ch{url}",
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
        return [listing for listing in (_to_listing(raw) for raw in raw_listings) if listing is not None]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise ScraperError(f"flatfox: Anfrage oder Verarbeitung fehlgeschlagen — {exc}") from exc
