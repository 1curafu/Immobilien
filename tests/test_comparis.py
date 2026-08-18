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


def test_parse_link_builds_listing_from_real_card_text_layout():
    # Real comparis.ch card layout, captured live 2026-08-17: the <a> itself
    # wraps the whole card — price, price-label, type, rooms/size, PLZ+Ort,
    # street, description, CTA — all as its own inner_text().
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/marktplatz/details/show/37839834"
    link.inner_text.return_value = (
        "CHF 950\nMietpreis pro Monat\n\nWG-Zimmer\n\n2 Zimmer, 50 m², 1. Etage\n\n"
        "8570 Weinfelden\n\nOststrasse 32\n\n2 private Zimmer (50 m²) mit eigenem Bad & WC\n\nAnfragen"
    )

    listing = _parse_link(link)

    assert listing.id == "comparis:37839834"
    assert listing.preis == 950.0
    assert listing.ort == "8570 Weinfelden"
    assert listing.zimmer == 2.0
    assert listing.titel == "WG-Zimmer"
    assert listing.url == "https://www.comparis.ch/immobilien/marktplatz/details/show/37839834"
    assert listing.quelle == "comparis"


def test_parse_link_falls_back_to_first_line_when_no_plz_present():
    link = MagicMock()
    link.get_attribute.return_value = "/immobilien/marktplatz/details/show/37785684"
    link.inner_text.return_value = "Mezikonerstrasse 7a\n4.5 Zimmer\nCHF 2’430.–"

    listing = _parse_link(link)

    assert listing.ort == "Mezikonerstrasse 7a"
    assert listing.preis == 2430.0
    assert listing.zimmer == 4.5


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
    link.inner_text.return_value = "Mezikonerstrasse 7a, 9542 Münchwilen TG\n4.5 Zimmer\nPreis auf Anfrage"

    assert _parse_link(link) is None
