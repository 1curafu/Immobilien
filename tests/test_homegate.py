from src.scrapers.base import SearchConfig


def test_scrape_calls_shared_platform_with_homegate_domain(mocker):
    mock_scrape_platform = mocker.patch("src.scrapers.homegate.scrape_platform", return_value=[])
    from src.scrapers.homegate import scrape

    config = SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None, rate_limit_sekunden=2)
    scrape(config, geocode_conn=None)

    mock_scrape_platform.assert_called_once_with("https://www.homegate.ch", "homegate", "Weinfelden", 2)
