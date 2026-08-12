from src.models import Listing
from src.scrapers.base import SearchConfig
from src.scrapers.homegate_platform import scrape_platform

BASE_URL = "https://www.immoscout24.ch"


def scrape(config: SearchConfig, geocode_conn) -> list[Listing]:
    return scrape_platform(BASE_URL, "immoscout24", config.stadt, config.rate_limit_sekunden)
