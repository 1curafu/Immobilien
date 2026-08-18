import re
import time
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from src.models import Listing
from src.scrapers.base import ScraperError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PRICE_RE = re.compile(r"CHF\s*([\d'’.]+)")


def _slugify_city(city: str) -> str:
    return city.strip().lower().replace(" ", "-")


def _parse_price(text: str) -> Optional[float]:
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    return float(digits) if digits else None


def _parse_rooms(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*Zimmer", text or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _build_search_url(
    base_url: str,
    path_template: str,
    city_slug: str,
    radius_km: float,
    preis_max: float,
    radius_param: str,
    price_param: str,
) -> str:
    # Native radius/price params found via search-engine-indexed real URLs
    # 2026-08-18 (homegate: be=<radius_m>&ah=<preis_max>, immoscout24:
    # r=<radius_m>&pt=<preis_max>) — appended after the robots.txt-required
    # an=G, still on the robots.txt-allowed "immobilien" path. Without these,
    # the scraper only ever searched the exact target city with no radius
    # expansion at all.
    path = path_template.format(city_slug=city_slug)
    radius_m = int(round(radius_km * 1000))
    return f"{base_url}{path}&{radius_param}={radius_m}&{price_param}={int(preis_max)}"


def _resolve_url(href: str, base_url: str, allowed_hosts: tuple[str, ...]) -> Optional[str]:
    absolute = href if href.startswith("http") else f"{base_url}{href}"
    if urlparse(absolute).hostname not in allowed_hosts:
        return None
    return absolute


def _parse_card(card, base_url: str, quelle: str, allowed_hosts: tuple[str, ...]) -> Optional[Listing]:
    link = card.query_selector('a[href*="/mieten/"]')
    if link is None:
        return None
    href = link.get_attribute("href") or ""
    id_match = re.search(r"/mieten/(\d+)", href)
    if id_match is None:
        return None
    listing_id = id_match.group(1)
    url = _resolve_url(href, base_url, allowed_hosts)
    if url is None:
        return None

    price_el = card.query_selector('[class*="HgListingCard_mainTitle"], [class*="HgListingCard_price"]')
    address_el = card.query_selector('[class*="HgListingCard_address"]')
    secondary_el = card.query_selector('[class*="HgListingCard_secondaryTitle"]')
    secondary_text = secondary_el.inner_text() if secondary_el else ""

    preis = _parse_price(price_el.inner_text() if price_el else "")
    if preis is None:
        return None

    return Listing(
        id=f"{quelle}:{listing_id}",
        titel=secondary_text.strip() or "Wohnung",
        preis=preis,
        ort=(address_el.inner_text() if address_el else "").strip(),
        zimmer=_parse_rooms(secondary_text),
        url=url,
        quelle=quelle,
    )


def scrape_platform(
    base_url: str,
    quelle: str,
    stadt: str,
    rate_limit_sekunden: float,
    allowed_hosts: tuple[str, ...],
    path_template: str,
    radius_km: float,
    preis_max: float,
    radius_param: str,
    price_param: str,
) -> list[Listing]:
    city_slug = _slugify_city(stadt)
    url = _build_search_url(
        base_url, path_template, city_slug, radius_km, preis_max, radius_param, price_param
    )

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
            listings = [_parse_card(card, base_url, quelle, allowed_hosts) for card in cards]
            browser.close()
    except PlaywrightError as exc:
        raise ScraperError(f"{quelle}: Ergebnisliste nicht ladbar (Layout geändert oder blockiert?) — {exc}") from exc

    time.sleep(rate_limit_sekunden)
    return [listing for listing in listings if listing is not None]
