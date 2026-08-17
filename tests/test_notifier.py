from unittest.mock import MagicMock

from src.models import Listing
from src.notifier import EmailConfig, build_html, build_subject, send_email


def _listing(preis=650.0, ort="Weinfelden", quelle="flatfox", url="https://example.com/1"):
    return Listing(id="flatfox:1", titel="Test", preis=preis, ort=ort, zimmer=2.5,
                   url=url, quelle=quelle)


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

    config = EmailConfig(gmail_address="a@gmail.com", gmail_app_password="secret", recipients=["b@gmail.com"])
    send_email(config, "Subject", "<p>Body</p>")

    mock_smtp.login.assert_called_once_with("a@gmail.com", "secret")
    assert mock_smtp.sendmail.called


def test_send_email_sends_to_multiple_recipients(mocker):
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    mocker.patch("src.notifier.smtplib.SMTP_SSL", return_value=mock_smtp)

    config = EmailConfig(
        gmail_address="a@gmail.com",
        gmail_app_password="secret",
        recipients=["b@gmail.com", "c@gmail.com"],
    )
    send_email(config, "Subject", "<p>Body</p>")

    to_addrs = mock_smtp.sendmail.call_args.args[1]
    assert to_addrs == ["b@gmail.com", "c@gmail.com"]
    message_string = mock_smtp.sendmail.call_args.args[2]
    assert "b@gmail.com, c@gmail.com" in message_string


def test_build_html_escapes_malicious_ort():
    """Regression test: HTML injection via listing.ort is escaped"""
    malicious_listing = _listing(ort="<b>Malicious</b>")
    html = build_html([malicious_listing], [])
    assert "&lt;b&gt;" in html
    assert "<b>Malicious</b>" not in html


def test_build_html_escapes_malicious_quelle():
    """Regression test: HTML injection via listing.quelle is escaped"""
    malicious_listing = _listing(quelle="<script>alert('xss')</script>")
    html = build_html([malicious_listing], [])
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_build_html_escapes_error_messages():
    """Regression test: HTML injection via error messages is escaped"""
    html = build_html([], ["<img src=x onerror='alert(1)'>"])
    assert "&lt;img" in html
    assert "<img src" not in html


def test_build_html_rejects_javascript_url():
    """Regression test: javascript: URLs are not rendered as clickable links"""
    malicious_listing = _listing(url="javascript:alert('xss')")
    html = build_html([malicious_listing], [])
    # javascript: URL should not appear in any href attribute
    assert 'href="javascript:' not in html
    # The URL should be displayed as escaped text, not as a clickable link
    assert "&#x27;" in html  # Single quote is escaped as HTML entity
