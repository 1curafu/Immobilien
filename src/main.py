import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import cooldown, dedupe, geocode as geo
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
    print(
        f"[immo-scraper] Suche: {search_config.stadt} +{search_config.radius_km:.0f}km, "
        f"preis_max=CHF {search_config.preis_max:.0f}, zimmer_min={search_config.zimmer_min}"
    )

    conn = dedupe.init_db(str(db_path))
    geo.init_geocode_cache(conn)
    cooldown.init_cooldown(conn)

    center = geo.geocode(conn, search_config.stadt)
    if center is None:
        raise SystemExit(f"Zielstadt '{search_config.stadt}' konnte nicht geokodiert werden.")
    print(f"[immo-scraper] Zielstadt geokodiert: {center[0]:.4f}, {center[1]:.4f}")

    cooldown_hours = float(raw_config["scraper"].get("cooldown_stunden", 3))

    all_listings = []
    errors = []
    for name in raw_config["scraper"]["aktiviert"]:
        if cooldown.is_in_cooldown(conn, name, cooldown_hours):
            hours_ago = cooldown.hours_since_failure(conn, name)
            message = (
                f"{name}: übersprungen (letzter Fehler vor {hours_ago:.1f}h, "
                f"Cooldown {cooldown_hours:.0f}h aktiv)"
            )
            errors.append(message)
            print(f"[immo-scraper] {message}")
            continue

        print(f"[immo-scraper] {name}: starte Suche...")
        scrape_fn = SCRAPERS[name]
        try:
            found = scrape_fn(search_config, conn)
            all_listings.extend(found)
            cooldown.clear_failure(conn, name)
            print(f"[immo-scraper] {name}: {len(found)} Treffer gefunden")
        except ScraperError as exc:
            errors.append(str(exc))
            cooldown.record_failure(conn, name)
            print(f"[immo-scraper] {name}: FEHLER — {exc}")
        except Exception as exc:  # noqa: BLE001 - a single scraper failing must never stop the run
            message = f"{name}: unerwarteter Fehler — {exc}"
            errors.append(message)
            cooldown.record_failure(conn, name)
            print(f"[immo-scraper] {message}")

    nearby = geo.filter_by_radius(conn, all_listings, center, search_config.radius_km)
    print(f"[immo-scraper] {len(all_listings)} Treffer insgesamt, {len(nearby)} im Umkreis von {search_config.radius_km:.0f}km")

    filtered = [
        listing for listing in nearby
        if listing.preis <= search_config.preis_max
        and (
            search_config.zimmer_min is None
            or (listing.zimmer is not None and listing.zimmer >= search_config.zimmer_min)
        )
    ]
    print(f"[immo-scraper] {len(filtered)} nach Preis-/Zimmerfilter")

    new_listings = dedupe.filter_new(conn, filtered)
    new_listings.sort(key=lambda listing: listing.preis)
    dedupe.mark_seen(conn, new_listings)
    print(f"[immo-scraper] {len(new_listings)} davon neu (noch nicht gemeldet)")

    should_send = new_listings or errors or not raw_config["email"]["nur_bei_treffern"]
    if should_send:
        recipient_env = os.environ.get("RECIPIENT_EMAIL")
        if recipient_env:
            recipients = [addr.strip() for addr in recipient_env.split(",") if addr.strip()]
        else:
            empfaenger = raw_config["email"]["empfaenger"]
            recipients = [empfaenger] if isinstance(empfaenger, str) else list(empfaenger)
        email_config = EmailConfig(
            gmail_address=os.environ["GMAIL_ADDRESS"],
            gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
            recipients=recipients,
        )
        send_email(email_config, build_subject(len(new_listings)), build_html(new_listings, errors))
        print(f"[immo-scraper] Email verschickt an: {', '.join(recipients)}")
    else:
        print("[immo-scraper] Keine Email verschickt (keine neuen Treffer, keine Fehler)")

    conn.close()


if __name__ == "__main__":
    run()
