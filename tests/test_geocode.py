import sqlite3

from src.geocode import bbox_around, filter_by_radius, geocode, haversine_km, init_geocode_cache
from src.models import Listing


def _conn():
    conn = sqlite3.connect(":memory:")
    init_geocode_cache(conn)
    return conn


def test_geocode_returns_cached_value_without_network(mocker):
    conn = _conn()
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.commit()
    mock_get = mocker.patch("src.geocode.httpx.get")

    result = geocode(conn, "Weinfelden")

    assert result == (47.5669187, 9.1097539)
    mock_get.assert_not_called()


def test_geocode_calls_nominatim_and_caches_result(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = [{"lat": "47.5669187", "lon": "9.1097539"}]
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")

    result = geocode(conn, "Weinfelden")

    assert result == (47.5669187, 9.1097539)
    cached = conn.execute("SELECT lat, lon FROM geocode_cache WHERE query = 'Weinfelden'").fetchone()
    assert cached == (47.5669187, 9.1097539)


def test_geocode_returns_none_when_nominatim_finds_nothing(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = []
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")

    assert geocode(conn, "Nirgendwo") is None


def test_haversine_zurich_to_bern_is_about_95km():
    distance = haversine_km(47.3769, 8.5417, 46.9480, 7.4474)
    assert 90 < distance < 100


def test_bbox_around_grows_with_radius():
    small = bbox_around(47.5669187, 9.1097539, 5)
    large = bbox_around(47.5669187, 9.1097539, 15)
    assert large["north"] - large["south"] > small["north"] - small["south"]
    assert small["south"] < 47.5669187 < small["north"]


def test_filter_by_radius_keeps_only_nearby_listings():
    conn = _conn()
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Zürich', 47.3769, 8.5417)")
    conn.commit()
    near = Listing(id="a", titel="near", preis=650, ort="Weinfelden", zimmer=None, url="https://x", quelle="flatfox")
    far = Listing(id="b", titel="far", preis=650, ort="Zürich", zimmer=None, url="https://y", quelle="flatfox")

    kept = filter_by_radius(conn, [near, far], center=(47.5669187, 9.1097539), radius_km=15)

    assert kept == [near]


def test_filter_by_radius_skips_listings_that_cannot_be_geocoded(mocker):
    conn = _conn()
    mock_response = mocker.Mock()
    mock_response.json.return_value = []
    mock_response.raise_for_status.return_value = None
    mocker.patch("src.geocode.httpx.get", return_value=mock_response)
    mocker.patch("src.geocode.time.sleep")
    unresolvable = Listing(id="c", titel="?", preis=650, ort="???", zimmer=None, url="https://z", quelle="flatfox")

    assert filter_by_radius(conn, [unresolvable], center=(47.5669187, 9.1097539), radius_km=15) == []
