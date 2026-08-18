from unittest.mock import MagicMock

from src.scrapers.homegate_platform import (
    _build_search_url,
    _parse_card,
    _parse_price,
    _parse_rooms,
    _slugify_city,
)

HOMEGATE_HOSTS = ("www.homegate.ch", "homegate.ch")
IMMOSCOUT24_HOSTS = ("www.immoscout24.ch", "immoscout24.ch")


def test_build_search_url_appends_radius_in_meters_and_price():
    url = _build_search_url(
        "https://www.homegate.ch",
        "/mieten/immobilien/ort-{city_slug}/trefferliste?an=G",
        "weinfelden",
        radius_km=15,
        preis_max=1000,
        radius_param="be",
        price_param="ah",
    )

    assert url == (
        "https://www.homegate.ch/mieten/immobilien/ort-weinfelden/trefferliste"
        "?an=G&be=15000&ah=1000"
    )


def test_build_search_url_uses_immoscout24_param_names():
    url = _build_search_url(
        "https://www.immoscout24.ch",
        "/de/immobilien/mieten/ort-{city_slug}?an=G",
        "weinfelden",
        radius_km=20,
        preis_max=650,
        radius_param="r",
        price_param="pt",
    )

    assert url == "https://www.immoscout24.ch/de/immobilien/mieten/ort-weinfelden?an=G&r=20000&pt=650"


def test_slugify_city_lowercases_and_hyphenates():
    assert _slugify_city("Weinfelden") == "weinfelden"
    assert _slugify_city("St. Gallen") == "st.-gallen"


def test_parse_price_extracts_digits():
    assert _parse_price("CHF 2'900.–") == 2900.0


def test_parse_price_returns_none_for_empty_text():
    assert _parse_price("") is None


def test_parse_price_returns_none_without_chf_prefix():
    assert _parse_price("4.5 Zimmer Wohnung") is None
    assert _parse_price("80 m²") is None


def test_parse_rooms_extracts_room_count():
    assert _parse_rooms("3.5 Zimmer, 80 m²") == 3.5


def test_parse_rooms_returns_none_when_absent():
    assert _parse_rooms("80 m²") is None


def _element(text):
    element = MagicMock()
    element.inner_text.return_value = text
    return element


def _card(*, href="/mieten/4003365027", price="CHF 2'900.–",
          address="Gaswerkstrasse 7, 8570 Weinfelden", secondary="3.5 Zimmer, 80 m²"):
    card = MagicMock()

    def query_selector(selector):
        if "href" in selector:
            link = MagicMock()
            link.get_attribute.return_value = href
            return link
        if "mainTitle" in selector or "price" in selector:
            return _element(price)
        if "address" in selector:
            return _element(address)
        if "secondaryTitle" in selector:
            return _element(secondary)
        return None

    card.query_selector.side_effect = query_selector
    return card


def test_parse_card_builds_listing_from_dom_elements():
    card = _card()

    listing = _parse_card(card, "https://www.homegate.ch", "homegate", HOMEGATE_HOSTS)

    assert listing.id == "homegate:4003365027"
    assert listing.preis == 2900.0
    assert listing.ort == "Gaswerkstrasse 7, 8570 Weinfelden"
    assert listing.zimmer == 3.5
    assert listing.url == "https://www.homegate.ch/mieten/4003365027"
    assert listing.quelle == "homegate"


def test_parse_card_returns_none_without_link():
    card = MagicMock()
    card.query_selector.return_value = None
    assert _parse_card(card, "https://www.homegate.ch", "homegate", HOMEGATE_HOSTS) is None


def test_parse_card_returns_none_for_absolute_off_host_url_with_matching_path():
    card = _card(href="https://evil.example/mieten/999999")

    assert _parse_card(card, "https://www.homegate.ch", "homegate", HOMEGATE_HOSTS) is None


def test_homegate_allowed_hosts_reject_immoscout24_url():
    card = _card(href="https://www.immoscout24.ch/mieten/4003365027")

    assert _parse_card(card, "https://www.homegate.ch", "homegate", HOMEGATE_HOSTS) is None


def test_immoscout24_allowed_hosts_reject_homegate_url():
    card = _card(href="https://www.homegate.ch/mieten/4003365027")

    assert _parse_card(card, "https://www.immoscout24.ch", "immoscout24", IMMOSCOUT24_HOSTS) is None


def test_parse_card_returns_none_when_price_unparseable():
    card = _card(price="Preis auf Anfrage")

    assert _parse_card(card, "https://www.homegate.ch", "homegate", HOMEGATE_HOSTS) is None
