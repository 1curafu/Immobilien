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
