# Immo-Scraper

Automatisierte tägliche Suche nach Mietwohnungen in der Schweiz über Flatfox,
Homegate, ImmoScout24 und Comparis. Filtert nach Preis und Umkreis der
Zielstadt, dedupliziert über Läufe hinweg und verschickt neue Treffer per
Email, sortiert nach Preis (aufsteigend).

> **wgzimmer.ch wird nicht automatisiert:** jede Suche dort ist per
> reCAPTCHA geschützt. Prüfe WG-Zimmer manuell unter
> [wgzimmer.ch](https://www.wgzimmer.ch/wgzimmer/search/mate.html).
>
> **Kein Captcha-Bypass:** Homegate, ImmoScout24 und Comparis sind hinter
> DataDome. Der Scraper verhält sich wie ein normaler Browser (echtes
> Chromium, keine Automatisierungs-Flags), löst aber keine aktiven
> Challenges — wenn ein Portal an einem Tag blockiert wird, wird dieses eine
> Portal für `scraper.cooldown_stunden` (Default 3h, in `config.yaml`)
> übersprungen, damit kein wiederholter Traffic gegen ein gerade
> blockiertes Portal läuft. Die anderen Portale und der Email-Versand laufen
> davon unberührt weiter.

## Setup (lokal)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env
```

Trage in `.env` deine Gmail-Adresse, dein Gmail-App-Passwort und die
Zieladresse ein (siehe unten, wie man ein App-Passwort erstellt).

Passe bei Bedarf `config.yaml` an (Stadt, Radius in km, Preislimit,
Mindest-Zimmerzahl) — keine Code-Kenntnisse nötig.

Lauf lokal starten:

```bash
python -m src.main
```

Tests laufen komplett offline (kein Netzwerk, kein Browserstart):

```bash
pytest -v
```

## Gmail App-Passwort erstellen

1. Zwei-Faktor-Authentifizierung für dein Google-Konto aktivieren (falls noch
   nicht geschehen): https://myaccount.google.com/security
2. App-Passwörter öffnen: https://myaccount.google.com/apppasswords
3. App "Mail" wählen, Passwort generieren, das 16-stellige Passwort in
   `GMAIL_APP_PASSWORD` eintragen (lokal in `.env`, im CI als GitHub Secret).

## GitHub Actions Secrets einrichten

Im Repo unter **Settings → Secrets and variables → Actions → New repository
secret** folgende drei Secrets anlegen:

- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`
- `RECIPIENT_EMAIL` — eine Adresse, oder mehrere kommagetrennt (z. B.
  `a@gmail.com, b@gmail.com`), um an mehrere Empfänger gleichzeitig zu senden.
  Überschreibt, wenn gesetzt, `email.empfaenger` aus `config.yaml`.

Der Workflow `.github/workflows/search.yml` läuft täglich um 07:00 Uhr
Europe/Zurich (Sommerzeit; im Winter ca. 06:00 Uhr lokal, da GitHub-Cron keine
Zeitzonen kennt). Zeit anpassen: den `cron`-Ausdruck in der Workflow-Datei
ändern (Format: UTC, `Minute Stunde * * *`).

Manuell auslösen: Tab **Actions** im Repo → Workflow **Immo Search** →
**Run workflow**.

## Architektur

Siehe [`docs/superpowers/specs/2026-08-11-immo-scraper-design.md`](docs/superpowers/specs/2026-08-11-immo-scraper-design.md)
für die vollständige Design-Doku (Datenfluss, Portal-Recherche, robots.txt-
Compliance je Portal).
