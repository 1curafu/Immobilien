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
