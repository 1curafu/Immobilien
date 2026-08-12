import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import dedupe, geocode as geo
from src.notifier import EmailConfig, build_html, build_subject, send_email
from src.scrapers import comparis, flatfox, homegate, immoscout24
from src.scrapers.base import ScraperError, SearchConfig

SCRAPERS = {
    "flatfox": flatfox.scrape,
    "homegate": homegate.scrape,
    "immoscout24": immoscout24.scrape,
    "comparis": comparis.scrape,
}

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
DEFAULT_DB_PATH = ROOT / "seen_listings.db"


def load_config(path: Path) -> tuple[SearchConfig, dict]:
    raw = yaml.safe_load(path.read_text())
    search_config = SearchConfig(
        stadt=raw["suche"]["stadt"],
        radius_km=float(raw["suche"]["radius_km"]),
        preis_max=float(raw["suche"]["preis_max"]),
        zimmer_min=raw["suche"]["zimmer_min"],
        rate_limit_sekunden=float(raw["scraper"]["rate_limit_sekunden"]),
    )
    return search_config, raw


def run(config_path: Path = DEFAULT_CONFIG_PATH, db_path: Path = DEFAULT_DB_PATH) -> None:
    load_dotenv()
    search_config, raw_config = load_config(config_path)

    conn = dedupe.init_db(str(db_path))
    geo.init_geocode_cache(conn)

    center = geo.geocode(conn, search_config.stadt)
    if center is None:
        raise SystemExit(f"Zielstadt '{search_config.stadt}' konnte nicht geokodiert werden.")

    all_listings = []
    errors = []
    for name in raw_config["scraper"]["aktiviert"]:
        scrape_fn = SCRAPERS[name]
        try:
            all_listings.extend(scrape_fn(search_config, conn))
        except ScraperError as exc:
            errors.append(str(exc))

    nearby = geo.filter_by_radius(conn, all_listings, center, search_config.radius_km)
    filtered = [
        listing for listing in nearby
        if listing.preis <= search_config.preis_max
        and (
            search_config.zimmer_min is None
            or (listing.zimmer is not None and listing.zimmer >= search_config.zimmer_min)
        )
    ]

    new_listings = dedupe.filter_new(conn, filtered)
    new_listings.sort(key=lambda listing: listing.preis)
    dedupe.mark_seen(conn, new_listings)

    should_send = new_listings or errors or not raw_config["email"]["nur_bei_treffern"]
    if should_send:
        email_config = EmailConfig(
            gmail_address=os.environ["GMAIL_ADDRESS"],
            gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
            recipient=raw_config["email"]["empfaenger"],
        )
        send_email(email_config, build_subject(len(new_listings)), build_html(new_listings, errors))

    conn.close()


if __name__ == "__main__":
    run()
