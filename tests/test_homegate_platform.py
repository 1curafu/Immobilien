from unittest.mock import MagicMock

from src.scrapers.homegate_platform import _parse_card, _parse_price, _parse_rooms, _slugify_city


def test_slugify_city_lowercases_and_hyphenates():
    assert _slugify_city("Weinfelden") == "weinfelden"
    assert _slugify_city("St. Gallen") == "st.-gallen"


def test_parse_price_extracts_digits():
    assert _parse_price("CHF 2'900.–") == 2900.0


def test_parse_price_returns_none_for_empty_text():
    assert _parse_price("") is None


def test_parse_rooms_extracts_room_count():
    assert _parse_rooms("3.5 Zimmer, 80 m²") == 3.5


def test_parse_rooms_returns_none_when_absent():
    assert _parse_rooms("80 m²") is None


def _element(text):
    element = MagicMock()
    element.inner_text.return_value = text
    return element


def test_parse_card_builds_listing_from_dom_elements():
    card = MagicMock()

    def query_selector(selector):
        if "href" in selector:
            link = MagicMock()
            link.get_attribute.return_value = "/mieten/4003365027"
            return link
        if "mainTitle" in selector or "price" in selector:
            return _element("CHF 2'900.–")
        if "address" in selector:
            return _element("Gaswerkstrasse 7, 8570 Weinfelden")
        if "secondaryTitle" in selector:
            return _element("3.5 Zimmer, 80 m²")
        return None

    card.query_selector.side_effect = query_selector

    listing = _parse_card(card, "https://www.homegate.ch", "homegate")

    assert listing.id == "homegate:4003365027"
    assert listing.preis == 2900.0
    assert listing.ort == "Gaswerkstrasse 7, 8570 Weinfelden"
    assert listing.zimmer == 3.5
    assert listing.url == "https://www.homegate.ch/mieten/4003365027"
    assert listing.quelle == "homegate"


def test_parse_card_returns_none_without_link():
    card = MagicMock()
    card.query_selector.return_value = None
    assert _parse_card(card, "https://www.homegate.ch", "homegate") is None
