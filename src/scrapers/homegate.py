from src.models import Listing
from src.scrapers.base import SearchConfig
from src.scrapers.homegate_platform import scrape_platform

BASE_URL = "https://www.homegate.ch"


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    return scrape_platform(
        BASE_URL,
        "homegate",
        config.stadt,
        config.rate_limit_sekunden,
        allowed_hosts=("www.homegate.ch", "homegate.ch"),
        path_template="/mieten/immobilien/ort-{city_slug}/trefferliste?an=G",
        radius_km=config.radius_km,
        preis_max=config.preis_max,
        radius_param="be",
        price_param="ah",
    )
