from src.models import Listing
from src.scrapers.base import SearchConfig
from src.scrapers.homegate_platform import scrape_platform

BASE_URL = "https://www.immoscout24.ch"

# Path shape confirmed 2026-08-18 via a search-engine-indexed real URL
# (https://www.immoscout24.ch/de/wohnung/mieten/ort-weinfelden?...), found
# without sending any request to immoscout24.ch itself. "immobilien" (real
# estate, all property types) and "wohnung" (flats only) are both valid
# top-level categories with the same /de/{type}/mieten/ort-{slug} shape;
# "immobilien" is used here since it's also the exact path robots.txt names
# in its allow-rule. A DataDome challenge on a given run is independent of
# this path being correct — see scrape_platform's error handling.
PATH_TEMPLATE = "/de/immobilien/mieten/ort-{city_slug}?an=G"


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    return scrape_platform(
        BASE_URL,
        "immoscout24",
        config.stadt,
        config.rate_limit_sekunden,
        allowed_hosts=("www.immoscout24.ch", "immoscout24.ch"),
        path_template=PATH_TEMPLATE,
        radius_km=config.radius_km,
        preis_max=config.preis_max,
        radius_param="r",
        price_param="pt",
    )
