# Immo-Scraper — Design

## Zweck

Automatisierte, tägliche Suche nach Mietwohnungen/-zimmern in der Schweiz über mehrere Portale, gefiltert nach Preis und Umkreis, mit Deduplizierung über Läufe hinweg. Ergebnisse werden per Email verschickt, sortiert nach Preis (aufsteigend).

## Suchparameter (Startkonfiguration)

- **Zielstadt:** Weinfelden
- **Radius:** 15 km
- **Preislimit:** CHF 650 / Monat
- **Mindest-Zimmerzahl:** keine (egal)
- **Ziel-Email:** icurafu333@gmail.com

Bei CHF 650 handelt es sich realistisch eher um ein WG-Zimmer als eine ganze Wohnung — Homegate, ImmoScout24, Comparis und Flatfox listen überwiegend ganze Wohnungen. Deshalb wird zusätzlich **wgzimmer.ch** (WG-Zimmer-Spezialist) als Quelle eingebunden.

## Tech-Stack

- Python 3.11+
- **Scraping:** `httpx` + `BeautifulSoup4` für statische Seiten (wgzimmer.ch, Flatfox); `playwright` (headless Chromium) für JS-lastige Portale (Homegate, ImmoScout24, Comparis)
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
│   │   ├── wgzimmer.py          # httpx + BeautifulSoup4 (statisch)
│   │   ├── flatfox.py           # httpx + BeautifulSoup4 (statisch)
│   │   ├── comparis.py          # Playwright (JS-lastig)
│   │   ├── homegate.py          # Playwright (JS-lastig)
│   │   └── immoscout24.py       # Playwright (JS-lastig)
│   ├── models.py                # Listing-Dataclass: titel, preis, ort, zimmer, url, quelle, id
│   ├── geocode.py                # Nominatim-Anbindung + geocode_cache (SQLite), Haversine-Distanz
│   ├── dedupe.py                 # SQLite: welche Listing-IDs wurden schon gemeldet
│   └── notifier.py               # baut HTML-Email (Tabelle nach Preis sortiert), sendet via SMTP
├── tests/
│   ├── fixtures/*.html           # gespeicherte Beispielseiten pro Portal
│   └── test_scrapers.py          # parst Fixtures offline, keine Live-Requests
└── .github/workflows/search.yml
```

### Datenfluss

1. `main.py` lädt `config.yaml` und `.env`
2. Für jeden aktivierten Scraper: `scrape()` in try/except aufrufen, mit Rate-Limit-Pause zwischen Requests und realistischem User-Agent pro Scraper. Ein fehlschlagender Scraper wird protokolliert (Portalname + Fehlermeldung), stoppt aber nicht die anderen.
3. Alle zurückgegebenen `Listing`-Objekte werden zu einer Liste zusammengeführt (einheitliches Format über alle Quellen)
4. **Umkreisfilter:** Zielstadt wird einmal pro Lauf via Nominatim geocodiert (lokal gecacht). Für jedes Listing wird der vom Portal gelieferte Ortsname ebenfalls geocodiert — Ergebnis dauerhaft in SQLite-Tabelle `geocode_cache` gespeichert, damit Nominatims 1-Request/Sekunde-Limit nur bei neuen, noch nicht gecachten Orten greift. Haversine-Distanz zur Zielstadt berechnen, alles außerhalb des Radius verwerfen. Portale mit nativer Umkreissuche (z. B. Homegate) nutzen deren Parameter zusätzlich als Vorfilter; Haversine bleibt die Ground-Truth-Filterung über alle Quellen hinweg.
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
  aktiviert: [wgzimmer, flatfox, comparis, homegate, immoscout24]
  rate_limit_sekunden: 2
```

### Robots.txt / RSS

Vor Implementierung jedes Scrapers wird kurz dokumentiert (Kommentar im jeweiligen Scraper-Modul + README-Abschnitt):
- ob und was `robots.txt` für den Scraping-Pfad erlaubt
- ob das Portal einen offiziellen RSS-/Alert-Feed anbietet — falls ja, wird dieser dem HTML-Scraping vorgezogen (stabiler, weniger Breakage-Risiko)

### Fehlerbehandlung

- Jeder Scraper wirft eigene Exceptions (z. B. `ScraperError`), `main.py` fängt sie pro Scraper ab
- Fehler werden gesammelt (Portalname + Meldung) und erscheinen als eigener Abschnitt in der Email (z. B. „⚠️ Fehler bei: ImmoScout24 — Layout geändert?")
- Kein Scraper-Fehler bricht den Gesamtlauf ab

### Testing

- Pro Portal ein gespeichertes HTML-Fixture unter `tests/fixtures/`
- `test_scrapers.py` parst Fixtures offline — keine Live-Requests während Tests
- Geocoding/Haversine-Logik wird mit festen Koordinaten-Paaren getestet (kein Live-Nominatim-Call in Tests)

## Bauphasen (für Implementierungsplan)

1. **Phase 1 — Vertikale Slice:** Pipeline-Skelett (`main.py`, `models.py`, `dedupe.py`, `geocode.py`, `notifier.py`) + `wgzimmer.py`-Scraper (statisch, httpx+BS4) end-to-end lauffähig, lokal getestet mit `.env`
2. **Phase 2:** `flatfox.py` (statisch) hinzufügen
3. **Phase 3:** `comparis.py`, `homegate.py`, `immoscout24.py` (Playwright, JS-lastig) einzeln hinzufügen, jeweils isoliert gegen Fixtures getestet
4. **Phase 4:** GitHub Actions Workflow (`search.yml`, täglich 07:00 Uhr Europe/Zurich), README (lokales Setup, `playwright install`, Gmail-App-Passwort erstellen, Cron anpassen), Secrets-Dokumentation

## Out of Scope (v1)

- Keine Web-UI/Dashboard — reine Email-Benachrichtigung
- Keine Unterstützung weiterer Länder/Regionen außerhalb der Schweiz
- Kein Retry-mit-Backoff bei transienten Netzwerkfehlern über den aktuellen Lauf hinaus (nächster Cron-Lauf greift ohnehin täglich)
