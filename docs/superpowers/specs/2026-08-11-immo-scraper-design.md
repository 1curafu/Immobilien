# Immo-Scraper — Design

## Zweck

Automatisierte, tägliche Suche nach Mietwohnungen/-zimmern in der Schweiz über mehrere Portale, gefiltert nach Preis und Umkreis, mit Deduplizierung über Läufe hinweg. Ergebnisse werden per Email verschickt, sortiert nach Preis (aufsteigend).

## Suchparameter (Startkonfiguration)

- **Zielstadt:** Weinfelden
- **Radius:** 15 km
- **Preislimit:** CHF 650 / Monat
- **Mindest-Zimmerzahl:** keine (egal)
- **Ziel-Email:** icurafu333@gmail.com

Bei CHF 650 handelt es sich realistisch eher um ein WG-Zimmer als eine ganze Wohnung — Homegate, ImmoScout24, Comparis und Flatfox listen überwiegend ganze Wohnungen. wgzimmer.ch wäre als WG-Zimmer-Spezialist naheliegend, scheidet aber aus (siehe unten).

### Recherche-Update: wgzimmer.ch ausgeschlossen

Live-Recherche der 5 ursprünglich vorgesehenen Portale ergab technische Fakten, die die Portalauswahl und Bauweise ändern:

- **wgzimmer.ch**: jede Suchanfrage — auch aus echtem Browser — wird durch **Google reCAPTCHA** blockiert (`"Das Verarbeiten der Anfrage wurde von Google reCaptcha gestoppt"`). Automatisiertes Scraping würde eine aktive Sicherheitsmaßnahme umgehen. **Wird nicht gebaut.** Stattdessen wird wgzimmer.ch in der README als manuell zu prüfende Quelle mit direktem Suchlink erwähnt.
- **flatfox.ch**: hat eine offene, öffentliche JSON-REST-API ohne Anti-Bot-Schutz (`GET /api/v1/pin/?east=&north=&south=&west=&offer_type=RENT` für Bounding-Box-Suche, dann `GET /api/v1/public-listing/?pk=<id>&...` für Details). Kein HTML-Scraping nötig — einfachster Fall, wird Phase 1.
- **comparis.ch, homegate.ch, immoscout24.ch**: alle drei hinter **DataDome** (blockt jeden reinen `curl`/`httpx`-Request mit 403; ein echter, nicht offensichtlich als Headless erkennbarer Playwright-Chromium kommt durch — normales Browsing, keine Umgehung eines Zugriffsschutzes gegen echte Nutzer). homegate.ch und immoscout24.ch laufen auf identischer Plattform (Swiss Marketplace Group) mit identischen `data-test`-Attributen — gleicher Scraper-Code, andere Domain.

Portalliste damit: **Flatfox (JSON API), Homegate, ImmoScout24, Comparis** — alle vier automatisierbar ohne Umgehung von Sicherheitsmaßnahmen.

## Tech-Stack

- Python 3.11+
- **Scraping:** `httpx` (reines JSON, keine HTML-Parsing nötig) für Flatfox' öffentliche API; `playwright` mit echtem, nicht als Headless erkennbarem Chromium (`headless=False` via Xvfb im CI, oder `channel="chrome"`) für die DataDome-geschützten Portale Homegate, ImmoScout24, Comparis
- **Geocoding:** `geopy` mit Nominatim (OpenStreetMap)
- **Persistenz:** SQLite (`seen_listings.db`) für Dedupe und Geocode-Cache
- **Scheduling:** GitHub Actions Cron (täglich 07:00 Uhr Europe/Zurich)
- **Email:** `smtplib` über Gmail SMTP mit App-Passwort
- **Config:** `config.yaml`
- **Secrets:** `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL` — GitHub Actions Secrets, lokal via `.env`

## Architektur

```
immo-scraper/
├── config.yaml
├── .env.example
├── requirements.txt
├── src/
│   ├── main.py                  # Orchestriert: scrape → normalisieren → geocode/radius-filter → dedupe → sortieren → mailen
│   ├── scrapers/
│   │   ├── base.py              # Scraper-Interface: scrape() -> list[Listing]
│   │   ├── homegate_platform.py # gemeinsame Playwright-Parsing-Logik für Homegate + ImmoScout24 (identische Plattform/DOM)
│   │   ├── flatfox.py           # httpx, öffentliche JSON-API (kein HTML-Parsing)
│   │   ├── comparis.py          # Playwright (DataDome-geschützt)
│   │   ├── homegate.py          # dünner Wrapper um homegate_platform.py, domain=homegate.ch
│   │   └── immoscout24.py       # dünner Wrapper um homegate_platform.py, domain=immoscout24.ch
│   ├── models.py                # Listing-Dataclass: titel, preis, ort, zimmer, url, quelle, id
│   ├── geocode.py                # Nominatim-Anbindung + geocode_cache (SQLite), Haversine-Distanz
│   ├── dedupe.py                 # SQLite: welche Listing-IDs wurden schon gemeldet
│   └── notifier.py               # baut HTML-Email (Tabelle nach Preis sortiert), sendet via SMTP
├── tests/
│   ├── fixtures/                 # gespeicherte JSON-/HTML-Beispiele pro Portal
│   └── test_scrapers.py          # parst Fixtures offline, keine Live-Requests
└── .github/workflows/search.yml
```

### Datenfluss

1. `main.py` lädt `config.yaml` und `.env`
2. Für jeden aktivierten Scraper: `scrape()` in try/except aufrufen, mit Rate-Limit-Pause zwischen Requests und realistischem User-Agent pro Scraper. Ein fehlschlagender Scraper wird protokolliert (Portalname + Fehlermeldung), stoppt aber nicht die anderen.
3. Alle zurückgegebenen `Listing`-Objekte werden zu einer Liste zusammengeführt (einheitliches Format über alle Quellen)
4. **Umkreisfilter:** Zielstadt wird einmal pro Lauf via Nominatim geocodiert (lokal gecacht). Für jedes Listing wird der vom Portal gelieferte Ortsname ebenfalls geocodiert — Ergebnis dauerhaft in SQLite-Tabelle `geocode_cache` gespeichert, damit Nominatims 1-Request/Sekunde-Limit nur bei neuen, noch nicht gecachten Orten greift. Haversine-Distanz zur Zielstadt berechnen, alles außerhalb des Radius verwerfen. Flatfox unterstützt nativ eine Bounding-Box-Vorfilterung (`/api/v1/pin/?east=&north=&south=&west=`, aus Zielstadt-Koordinaten ± Radius berechnet) — Haversine bleibt trotzdem die Ground-Truth-Filterung über alle Quellen hinweg, da eine Bounding-Box kein exakter Kreis ist.
5. **Preis-/Zimmerfilter:** Listings über dem Preislimit bzw. unter der Mindest-Zimmerzahl werden verworfen
6. **Dedupe:** gegen `seen_listings.db` prüfen, welche IDs bereits gemeldet wurden; nur neue Listings weiterreichen; neue IDs anschließend als gesehen markieren
7. **Sortierung:** neue Listings nach Preis aufsteigend sortieren
8. **Notifier:** HTML-Email bauen (Tabelle: Preis, Ort, Zimmer, Link, Quelle) inkl. Anzahl neuer Treffer und ggf. Fehlerabschnitt; per SMTP verschicken. Wenn alle Scraper fehlschlagen, wird trotzdem eine Email mit Fehlerbericht verschickt (kein stiller Fail). Wenn keine neuen Treffer und keine Fehler vorliegen, wird standardmäßig **keine** Email verschickt; steuerbar über `email.nur_bei_treffern` in `config.yaml` (Default: `true`).

### Config-Schema (`config.yaml`)

```yaml
suche:
  stadt: "Weinfelden"
  radius_km: 15
  preis_max: 650
  zimmer_min: null   # null = keine Mindestanforderung
email:
  empfaenger: "icurafu333@gmail.com"
  nur_bei_treffern: true   # false = auch Emails ohne neue Treffer verschicken
scraper:
  aktiviert: [flatfox, comparis, homegate, immoscout24]
  rate_limit_sekunden: 2
```

### Robots.txt-Compliance je Portal (recherchiert, verbindlich für Implementierung)

- **Flatfox:** `robots.txt` erlaubt `/` (bis auf `/admin/`, `/*/partner/`, `/*/cockpit/` — nicht betroffen). API-Nutzung unkritisch.
- **Homegate & ImmoScout24:** `robots.txt` disallowed generisch `/*?*an=`, erlaubt aber explizit `/mieten/immobilien/*/trefferliste?an=G` (Homegate) bzw. `/de/immobilien/mieten/*?an=G` (ImmoScout24). Der Scraper **muss** den Query-Parameter `an=G` an jede Trefferlisten-URL anhängen, sonst außerhalb des erlaubten Pfads.
- **Comparis:** `robots.txt` disallowed `/immobilien/api/`, `/immobilien/searchservice/`, `/immobilien/details/`, `/immobilien/dataProvider/` — nicht aber `/immobilien/result/list`. Der Scraper **muss** die HTML-Route `/immobilien/result/list` verwenden, nicht den (schnelleren, aber gesperrten) JSON-Zwilling `/immobilien/api/v1/singlepage/secondLevelPage`.
- **wgzimmer.ch:** kein RSS/API gefunden, jede Suche reCAPTCHA-gesperrt — daher nicht automatisiert (siehe oben), in README als manuelle Quelle verlinkt.

### Fehlerbehandlung

- Jeder Scraper wirft eigene Exceptions (z. B. `ScraperError`), `main.py` fängt sie pro Scraper ab
- Fehler werden gesammelt (Portalname + Meldung) und erscheinen als eigener Abschnitt in der Email (z. B. „⚠️ Fehler bei: ImmoScout24 — Layout geändert?")
- Kein Scraper-Fehler bricht den Gesamtlauf ab

### Testing

- **Flatfox:** gespeicherte Beispiel-JSON-Responses unter `tests/fixtures/flatfox_pins.json` und `tests/fixtures/flatfox_listings.json`, `httpx`-Client in Tests gemockt (kein Live-Call)
- **Homegate/ImmoScout24/Comparis:** gespeicherte HTML-Fixtures unter `tests/fixtures/*.html` (mit Playwright einmalig live erzeugt, dann eingecheckt), Parsing-Logik wird gegen das eingecheckte HTML getestet statt gegen eine Live-Seite
- `test_scrapers.py` läuft komplett offline — keine Live-Requests, kein Playwright-Browserstart während Tests
- Geocoding/Haversine-Logik wird mit festen Koordinaten-Paaren getestet (kein Live-Nominatim-Call in Tests)

## Bauphasen (für Implementierungsplan)

1. **Phase 1 — Vertikale Slice:** Pipeline-Skelett (`main.py`, `models.py`, `dedupe.py`, `geocode.py`, `notifier.py`) + `flatfox.py`-Scraper (httpx, JSON-API, kein Browser nötig) end-to-end lauffähig, lokal getestet mit `.env`
2. **Phase 2:** `homegate_platform.py` (gemeinsame Playwright-Parsing-Logik, `data-test="result-list-item"`-Selektoren) + `homegate.py`-Wrapper hinzufügen
3. **Phase 3:** `immoscout24.py` (dünner Wrapper um `homegate_platform.py`, andere Domain) + `comparis.py` (Playwright, eigene Parsing-Logik da andere Plattform) hinzufügen
4. **Phase 4:** GitHub Actions Workflow (`search.yml`, täglich 07:00 Uhr Europe/Zurich), README (lokales Setup, `playwright install`, Gmail-App-Passwort erstellen, Cron anpassen, Hinweis auf wgzimmer.ch als manuell zu prüfende Quelle), Secrets-Dokumentation

## Out of Scope (v1)

- Keine Web-UI/Dashboard — reine Email-Benachrichtigung
- Keine Unterstützung weiterer Länder/Regionen außerhalb der Schweiz
- Kein Retry-mit-Backoff bei transienten Netzwerkfehlern über den aktuellen Lauf hinaus (nächster Cron-Lauf greift ohnehin täglich)
