import json
import urllib.parse
from unittest.mock import MagicMock

from src.scrapers.comparis import build_request_object, build_search_url, _parse_link, _parse_price, _parse_rooms


def test_build_request_object_sets_rent_deal_type_and_price_ceiling():
    bbox = {"north": 47.7, "south": 47.4, "east": 9.3, "west": 8.9}

    request_object = build_request_object("Weinfelden", 650, bbox)

    assert request_object["DealType"] == 10
    assert request_object["PriceTo"] == 650
    assert request_object["LocationSearchString"] == "Weinfelden"
    assert request_object["UpperRightLatitude"] == 47.7
    assert request_object["LowerLeftLongitude"] == 8.9


def test_build_search_url_embeds_encoded_request_object():
    request_object = {"DealType": 10, "LocationSearchString": "Weinfelden"}

    url = build_search_url(request_object)

    assert url.startswith("https://www.comparis.ch/immobilien/result/list?requestobject=")
    encoded = url.split("requestobject=")[1]
    assert json.loads(urllib.parse.unquote(encoded)) == request_object


def test_parse_price_handles_swiss_thousands_separator():
    assert _parse_price("CHF 2’430.– pro Monat") == 2430.0


def test_parse_price_returns_none_without_chf_amount():
    assert _parse_price("Details anzeigen") is None


def test_parse_rooms_extracts_room_count():
    assert _parse_rooms("4.5 Zimmer, 102 m²") == 4.5


def test_parse_link_builds_listing_from_container_text():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/marktplatz/details/show/37785684"
    container = MagicMock()
    container.inner_text.return_value = "Mezikonerstrasse 7a, 9542 Münchwilen TG\n4.5 Zimmer\nCHF 2’430.–"
    handle = MagicMock()
    handle.as_element.return_value = container
    link.evaluate_handle.return_value = handle

    listing = _parse_link(link)

    assert listing.id == "comparis:37785684"
    assert listing.preis == 2430.0
    assert listing.ort == "Mezikonerstrasse 7a, 9542 Münchwilen TG"
    assert listing.zimmer == 4.5
    assert listing.url == "https://www.comparis.ch/immobilien/marktplatz/details/show/37785684"
    assert listing.quelle == "comparis"


def test_parse_link_returns_none_for_non_listing_link():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/some-other-page"

    assert _parse_link(link) is None


def test_parse_link_returns_none_for_untrusted_host_with_matching_path():
    link = MagicMock()
    link.get_attribute.return_value = "https://evil.example/immobilien/marktplatz/details/show/999"

    assert _parse_link(link) is None


def test_parse_link_returns_none_when_price_unparseable():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/marktplatz/details/show/37785684"
    container = MagicMock()
    container.inner_text.return_value = "Mezikonerstrasse 7a, 9542 Münchwilen TG\n4.5 Zimmer\nPreis auf Anfrage"
    handle = MagicMock()
    handle.as_element.return_value = container
    link.evaluate_handle.return_value = handle

    assert _parse_link(link) is None
