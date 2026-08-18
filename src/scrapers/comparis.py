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
# Swiss postal code + place name, e.g. "8570 Weinfelden" — anchors ort-extraction
# to a semantic pattern rather than a fixed line position (verified 2026-08-17
# against real comparis.ch cards: the card's line order is price, price-label,
# property type, rooms/size, PLZ+Ort, street, description, CTA).
PLZ_ORT_RE = re.compile(r"\b\d{4}\s+[A-ZÀ-Ý][\wÀ-ÿ'.\- ]*")


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


def _resolve_comparis_url(href: str) -> Optional[str]:
    absolute = href if href.startswith("http") else f"{BASE_URL}{href}"
    parsed = urllib.parse.urlparse(absolute)
    if parsed.hostname not in ("www.comparis.ch", "comparis.ch"):
        return None
    return absolute


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or PRICE_RE.search(line) or "mietpreis" in line.lower() or PLZ_ORT_RE.match(line):
            continue
        return line
    return "Wohnung"


def _extract_ort(text: str) -> str:
    match = PLZ_ORT_RE.search(text)
    if match:
        return match.group(0).strip()
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _parse_link(link) -> Optional[Listing]:
    href = link.get_attribute("href") or ""
    id_match = ID_RE.search(href)
    if id_match is None:
        return None

    url = _resolve_comparis_url(href)
    if url is None:
        return None

    # The result-list anchor wraps the entire card's content (verified against
    # real comparis.ch HTML on 2026-08-17) — no ancestor walk needed, and
    # walking up risks concatenating sibling cards' text together.
    text = link.inner_text() or ""

    preis = _parse_price(text)
    if preis is None:
        return None

    return Listing(
        id=f"comparis:{id_match.group(1)}",
        titel=_extract_title(text),
        preis=preis,
        ort=_extract_ort(text),
        zimmer=_parse_rooms(text),
        url=url,
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
