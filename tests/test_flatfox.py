import json
import sqlite3
from pathlib import Path

import pytest

from src.geocode import init_geocode_cache
from src.scrapers import flatfox
from src.scrapers.base import ScraperError, SearchConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _config():
    return SearchConfig(stadt="Weinfelden", radius_km=15, preis_max=650, zimmer_min=None)


def _conn_with_weinfelden_cached():
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.commit()
    return conn


def test_to_listing_maps_real_flatfox_fields():
    raw = json.loads((FIXTURES / "flatfox_listings.json").read_text())["results"][0]

    listing = flatfox._to_listing(raw)

    assert listing.id == "flatfox:86263289"
    assert listing.preis == 2430.0
    assert listing.zimmer == 4.0
    assert listing.ort == "Münchwilen TG"
    assert listing.url == "https://flatfox.ch/en/flat/mezikonerstrassw-7a-9542-munchwilen-tg/86263289/"
    assert listing.quelle == "flatfox"


def test_to_listing_handles_missing_room_count():
    raw = {"pk": 1, "url": "/x/1/", "price_display": 650, "number_of_rooms": None,
           "city": "Weinfelden", "short_title": "Studio", "public_title": "Studio"}

    listing = flatfox._to_listing(raw)

    assert listing.zimmer is None


def test_scrape_returns_listings_from_mocked_api(mocker):
    pins = json.loads((FIXTURES / "flatfox_pins.json").read_text())
    listings_response = json.loads((FIXTURES / "flatfox_listings.json").read_text())

    mock_pins_response = mocker.Mock()
    mock_pins_response.json.return_value = pins
    mock_pins_response.raise_for_status.return_value = None

    mock_listings_response = mocker.Mock()
    mock_listings_response.json.return_value = listings_response
    mock_listings_response.raise_for_status.return_value = None

    mock_client = mocker.MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [mock_pins_response, mock_listings_response]
    mocker.patch("src.scrapers.flatfox.httpx.Client", return_value=mock_client)

    result = flatfox.scrape(_config(), _conn_with_weinfelden_cached())

    assert len(result) == 2
    assert all(listing.quelle == "flatfox" for listing in result)


def test_scrape_raises_scraper_error_when_city_not_geocodable(mocker):
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    empty_response = mocker.Mock()
    empty_response.json.return_value = []
    empty_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=empty_response)
    mocker.patch("src.geocode.time.sleep")

    with pytest.raises(ScraperError):
        flatfox.scrape(_config(), conn)


def test_scrape_raises_scraper_error_on_http_failure(mocker):
    import httpx as httpx_module

    mock_client = mocker.MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = httpx_module.HTTPError("boom")
    mocker.patch("src.scrapers.flatfox.httpx.Client", return_value=mock_client)

    with pytest.raises(ScraperError):
        flatfox.scrape(_config(), _conn_with_weinfelden_cached())


def test_fetch_listing_details_chunks_requests_past_chunk_size(mocker):
    pks = list(range(1, 151))  # 150 pks -> 2 chunks of CHUNK_SIZE=100

    first_chunk_response = mocker.Mock()
    first_chunk_response.json.return_value = {"results": [{"pk": pk} for pk in pks[:100]]}
    first_chunk_response.raise_for_status.return_value = None

    second_chunk_response = mocker.Mock()
    second_chunk_response.json.return_value = {"results": [{"pk": pk} for pk in pks[100:]]}
    second_chunk_response.raise_for_status.return_value = None

    mock_client = mocker.MagicMock()
    mock_client.get.side_effect = [first_chunk_response, second_chunk_response]

    results = flatfox._fetch_listing_details(mock_client, pks)

    assert mock_client.get.call_count == 2
    assert len(results) == 150
    first_call_params = mock_client.get.call_args_list[0].kwargs["params"]
    assert len([p for p in first_call_params if p[0] == "pk"]) == 100
    second_call_params = mock_client.get.call_args_list[1].kwargs["params"]
    assert len([p for p in second_call_params if p[0] == "pk"]) == 50


def test_scrape_raises_scraper_error_on_malformed_listing(mocker):
    pins = [{"pk": 1}]
    malformed_response = {
        "results": [
            {"pk": 1, "url": "/x/1/", "number_of_rooms": "1.0",
             "city": "Weinfelden", "short_title": "Flat"}
            # Missing price_display — will cause KeyError in _to_listing
        ]
    }

    mock_pins_response = mocker.Mock()
    mock_pins_response.json.return_value = pins
    mock_pins_response.raise_for_status.return_value = None

    mock_listings_response = mocker.Mock()
    mock_listings_response.json.return_value = malformed_response
    mock_listings_response.raise_for_status.return_value = None

    mock_client = mocker.MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [mock_pins_response, mock_listings_response]
    mocker.patch("src.scrapers.flatfox.httpx.Client", return_value=mock_client)

    with pytest.raises(ScraperError):
        flatfox.scrape(_config(), _conn_with_weinfelden_cached())
