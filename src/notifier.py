import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import urlparse

from src.models import Listing


@dataclass
class EmailConfig:
    gmail_address: str
    gmail_app_password: str
    recipient: str


def build_subject(new_count: int) -> str:
    if new_count == 0:
        return "Immo-Scraper: keine neuen Treffer"
    return f"Immo-Scraper: {new_count} neue Treffer"


def build_html(listings: list[Listing], errors: list[str]) -> str:
    if listings:
        rows = []
        for listing in listings:
            # Validate URL scheme (only http/https allowed)
            parsed_url = urlparse(listing.url)
            if parsed_url.scheme in ("http", "https"):
                link_html = f"<a href=\"{escape(listing.url, quote=True)}\">Inserat</a>"
            else:
                # Non-http(s) URL: render as escaped text without href
                link_html = escape(listing.url)

            row = (
                f"<tr><td>CHF {listing.preis:.0f}</td><td>{escape(listing.ort)}</td>"
                f"<td>{listing.zimmer if listing.zimmer is not None else '-'}</td>"
                f"<td>{link_html}</td><td>{escape(listing.quelle)}</td></tr>"
            )
            rows.append(row)

        table = (
            "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
            "<tr><th>Preis</th><th>Ort</th><th>Zimmer</th><th>Link</th><th>Quelle</th></tr>"
            f"{''.join(rows)}</table>"
        )
    else:
        table = "<p>Keine neuen Treffer.</p>"

    error_section = ""
    if errors:
        items = "".join(f"<li>{escape(error)}</li>" for error in errors)
        error_section = f"<h3>⚠️ Fehler bei folgenden Scrapern</h3><ul>{items}</ul>"

    return f"<h2>{len(listings)} neue Treffer</h2>{table}{error_section}"


def send_email(config: EmailConfig, subject: str, html_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.gmail_address
    message["To"] = config.recipient
    message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config.gmail_address, config.gmail_app_password)
        server.sendmail(config.gmail_address, [config.recipient], message.as_string())
