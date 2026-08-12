from src.scrapers.base import SearchConfig


def test_scrape_calls_shared_platform_with_immoscout24_domain(mocker):
    mock_scrape_platform = mocker.patch("src.scrapers.immoscout24.scrape_platform", return_value=[])
    from src.scrapers.immoscout24 import scrape

    config = SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None, rate_limit_sekunden=2)
    scrape(config, geocode_conn=None)

    mock_scrape_platform.assert_called_once_with("https://www.immoscout24.ch", "immoscout24", "Weinfelden", 2)
