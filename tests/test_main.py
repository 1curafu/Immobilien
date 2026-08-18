import sqlite3
from pathlib import Path

import yaml

from src.geocode import init_geocode_cache
from src.models import Listing
from src.scrapers.base import ScraperError


def _write_config(tmp_path: Path) -> Path:
    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near", "fake_far", "fake_broken"], "rate_limit_sekunden": 0},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def _seed_geocode_cache(db_path: Path, *, include_zurich: bool) -> None:
    conn = sqlite3.connect(str(db_path))
    init_geocode_cache(conn)
    conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Weinfelden', 47.5669187, 9.1097539)")
    if include_zurich:
        conn.execute("INSERT INTO geocode_cache (query, lat, lon) VALUES ('Zürich', 47.3769, 8.5417)")
    conn.commit()
    conn.close()


def test_run_sends_email_with_only_new_nearby_affordable_listings(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    far = Listing(id="fake:far", titel="Far", preis=600, ort="Zürich", zimmer=None,
                   url="https://x/2", quelle="fake_far")

    def broken_scrape(config, conn):
        raise ScraperError("fake_broken: Layout geändert?")

    mocker.patch("src.main.SCRAPERS", {
        "fake_near": lambda config, conn: [near],
        "fake_far": lambda config, conn: [far],
        "fake_broken": broken_scrape,
    })
    sent = {}
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent.update(subject=subject, html=html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config_path = _write_config(tmp_path)
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=True)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert "Weinfelden" in sent["html"]
    assert "Zürich" not in sent["html"]
    assert "fake_broken: Layout geändert?" in sent["html"]


def test_run_does_not_resend_already_seen_listing(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: [near]})
    sent_calls = []
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent_calls.append(html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })
    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)
    main.run(config_path=config_path, db_path=db_path)

    assert len(sent_calls) == 1  # second run found nothing new, nur_bei_treffern=True suppresses the email


def test_run_skips_email_when_no_hits_and_no_errors(tmp_path, mocker):
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: []})
    send_mock = mocker.patch("src.main.send_email")
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })
    config_path = _write_config(tmp_path)
    config_path.write_text(yaml.safe_dump({
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    send_mock.assert_not_called()


def test_run_prefers_recipient_email_env_var_over_config_file(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: [near]})
    sent_configs = []
    mocker.patch(
        "src.main.send_email",
        side_effect=lambda cfg, subject, html: sent_configs.append(cfg),
    )
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com",
        "GMAIL_APP_PASSWORD": "secret",
        "RECIPIENT_EMAIL": "env-recipient@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "config-recipient@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert len(sent_configs) == 1
    assert sent_configs[0].recipients == ["env-recipient@example.com"]


def test_run_splits_comma_separated_recipient_email_env_var(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: [near]})
    sent_configs = []
    mocker.patch(
        "src.main.send_email",
        side_effect=lambda cfg, subject, html: sent_configs.append(cfg),
    )
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com",
        "GMAIL_APP_PASSWORD": "secret",
        "RECIPIENT_EMAIL": "one@example.com, two@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "config-recipient@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert sent_configs[0].recipients == ["one@example.com", "two@example.com"]


def test_run_supports_list_of_recipients_in_config_file(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: [near]})
    sent_configs = []
    mocker.patch(
        "src.main.send_email",
        side_effect=lambda cfg, subject, html: sent_configs.append(cfg),
    )
    # Real repo .env (if present) must not leak into this test — it deliberately
    # omits RECIPIENT_EMAIL to exercise the config.yaml fallback path.
    mocker.patch("src.main.load_dotenv")
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com",
        "GMAIL_APP_PASSWORD": "secret",
    }, clear=True)

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": ["one@example.com", "two@example.com"], "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert sent_configs[0].recipients == ["one@example.com", "two@example.com"]


def test_run_continues_and_reports_error_when_scraper_raises_plain_exception(tmp_path, mocker):
    near = Listing(id="fake:near", titel="Near", preis=600, ort="Weinfelden", zimmer=None,
                    url="https://x/1", quelle="fake_near")

    def broken_scrape(config, conn):
        raise AttributeError("fake_broken: unexpected AttributeError")

    mocker.patch("src.main.SCRAPERS", {
        "fake_near": lambda config, conn: [near],
        "fake_broken": broken_scrape,
    })
    sent = {}
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent.update(html=html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near", "fake_broken"], "rate_limit_sekunden": 0},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    from src import main
    main.run(config_path=config_path, db_path=db_path)  # must not raise

    assert "fake_broken" in sent["html"]
    assert "unexpected AttributeError" in sent["html"]


def test_run_skips_scraper_still_in_cooldown_after_recent_failure(tmp_path, mocker):
    call_count = {"n": 0}

    def fake_near_scrape(config, conn):
        call_count["n"] += 1
        return []

    mocker.patch("src.main.SCRAPERS", {"fake_near": fake_near_scrape})
    sent = {}
    mocker.patch("src.main.send_email", side_effect=lambda cfg, subject, html: sent.update(html=html))
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0, "cooldown_stunden": 3},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    conn = sqlite3.connect(str(db_path))
    from src.cooldown import init_cooldown, record_failure
    init_cooldown(conn)
    record_failure(conn, "fake_near")
    conn.close()

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert call_count["n"] == 0
    assert "übersprungen" in sent["html"]


def test_run_calls_scraper_again_after_cooldown_expires(tmp_path, mocker):
    call_count = {"n": 0}

    def fake_near_scrape(config, conn):
        call_count["n"] += 1
        return []

    mocker.patch("src.main.SCRAPERS", {"fake_near": fake_near_scrape})
    mocker.patch("src.main.send_email")
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0, "cooldown_stunden": 3},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    conn = sqlite3.connect(str(db_path))
    from src.cooldown import init_cooldown
    init_cooldown(conn)
    conn.execute(
        "INSERT INTO scraper_failures (name, failed_at) VALUES ('fake_near', datetime('now', '-5 hours'))"
    )
    conn.commit()
    conn.close()

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    assert call_count["n"] == 1


def test_run_clears_cooldown_after_successful_scrape(tmp_path, mocker):
    mocker.patch("src.main.SCRAPERS", {"fake_near": lambda config, conn: []})
    mocker.patch("src.main.send_email")
    mocker.patch.dict("os.environ", {
        "GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "secret", "RECIPIENT_EMAIL": "test@example.com",
    })

    config = {
        "suche": {"stadt": "Weinfelden", "radius_km": 15, "preis_max": 650, "zimmer_min": None},
        "email": {"empfaenger": "test@example.com", "nur_bei_treffern": True},
        "scraper": {"aktiviert": ["fake_near"], "rate_limit_sekunden": 0, "cooldown_stunden": 3},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    db_path = tmp_path / "seen.db"
    _seed_geocode_cache(db_path, include_zurich=False)

    # A failure old enough to be past cooldown: the scraper still runs (and
    # succeeds), and the stale failure row should be cleared afterward.
    conn = sqlite3.connect(str(db_path))
    from src.cooldown import init_cooldown
    init_cooldown(conn)
    conn.execute(
        "INSERT INTO scraper_failures (name, failed_at) VALUES ('fake_near', datetime('now', '-5 hours'))"
    )
    conn.commit()
    conn.close()

    from src import main
    main.run(config_path=config_path, db_path=db_path)

    from src.cooldown import is_in_cooldown
    conn2 = sqlite3.connect(str(db_path))
    assert is_in_cooldown(conn2, "fake_near", cooldown_hours=3) is False
    row = conn2.execute("SELECT COUNT(*) FROM scraper_failures WHERE name = 'fake_near'").fetchone()
    assert row[0] == 0
