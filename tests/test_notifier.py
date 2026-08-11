from unittest.mock import MagicMock

from src.models import Listing
from src.notifier import EmailConfig, build_html, build_subject, send_email


def _listing(preis=650.0, ort="Weinfelden", quelle="flatfox"):
    return Listing(id="flatfox:1", titel="Test", preis=preis, ort=ort, zimmer=2.5,
                   url="https://example.com/1", quelle=quelle)


def test_build_subject_with_no_hits():
    assert build_subject(0) == "Immo-Scraper: keine neuen Treffer"


def test_build_subject_with_hits():
    assert build_subject(3) == "Immo-Scraper: 3 neue Treffer"


def test_build_html_includes_listing_row():
    html = build_html([_listing()], [])
    assert "CHF 650" in html
    assert "Weinfelden" in html
    assert "flatfox" in html


def test_build_html_shows_empty_state():
    html = build_html([], [])
    assert "Keine neuen Treffer" in html


def test_build_html_includes_error_section():
    html = build_html([], ["homegate: Layout geändert?"])
    assert "Fehler" in html
    assert "homegate: Layout geändert?" in html


def test_send_email_logs_in_and_sends(mocker):
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    mocker.patch("src.notifier.smtplib.SMTP_SSL", return_value=mock_smtp)

    config = EmailConfig(gmail_address="a@gmail.com", gmail_app_password="secret", recipient="b@gmail.com")
    send_email(config, "Subject", "<p>Body</p>")

    mock_smtp.login.assert_called_once_with("a@gmail.com", "secret")
    assert mock_smtp.sendmail.called
