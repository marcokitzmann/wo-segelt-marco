# Wo segelt Marco? 🚢

<img src="images/bobblehead-marco.jpg" alt="Marco Bobblehead" width="200" align="right" style="margin-left: 1.5rem; border-radius: 12px;" />

Verfolgt die Position der **Roald Amundsen** (MMSI 211215170) auf einer interaktiven Karte.
Quelle: [marinetraffic.live](https://marinetraffic.live/vessels/roald-amundsen-position/211215170/)

## Live-Seite

→ **https://marcokitzmann.github.io/wo-segelt-marco/**

<br clear="right" />

## Features

- Interaktive Karte (MapLibre GL) mit aktueller Schiffsposition und historischer Route (letzten 30 Tage)
- Sidebar mit zwei Tabs:
  - **Status** – Marco-an-Bord-Banner (konfiguierbar per `config.json`)
  - **Schiff & Wetter** – Position, Geschwindigkeit, Kurs, Navigationsstatus, Abfahrts-/Zielhafen, ATD & ETA
- Aktuelles Wetter an der letzten Position (Temperatur, Wind, Bewölkung, Niederschlag, Sichtweite) via OpenWeatherMap
- Automatisches Daten-Update **jede Stunde** per GitHub Action (täglich ~24 Scraper-Läufe)
- Manueller Trigger des Workflows mit optionaler Debug-Ausgabe möglich
- Responsives Design, funktioniert auf Desktop und Mobilgeräten

## Marco-Schalter

In `config.json` den Wert setzen:

```json
{ "marco_sailing": true }   ← Marco ist an Bord
{ "marco_sailing": false }  ← Marco ist an Land
```

Datei committen & pushen – die Seite zeigt sofort das passende Banner.

## Projektstruktur

```
wo-segelt-marco/
├── index.html              # Hauptseite (MapLibre GL, zweispaltig mit Sidebar)
├── style.css               # Styling
├── app.js                  # Kartenlogik, Daten laden, UI
├── config.json             # Marco-an-Bord-Schalter
├── data/
│   ├── position.json       # Aktuelle Schiffsposition (stündlich aktualisiert)
│   ├── history.json        # Positionshistorie (max. 720 Einträge ≈ 30 Tage)
│   └── weather.json        # Wetterdaten an letzter Position
├── images/
│   └── bobblehead-marco.jpg
├── scripts/
│   └── scrape.py           # Playwright-Scraper (marinetraffic.live)
├── requirements.txt
└── .github/workflows/
    └── scrape.yml          # GitHub Action: stündlicher Scraper-Lauf
```

## GitHub Actions Workflow

Der Workflow läuft automatisch **jede Stunde (10 Minuten nach der vollen Stunde)** und kann auch manuell über die GitHub-Oberfläche gestartet werden (mit optionaler Debug-Ausgabe).

Er scrapt Position und Wetter, committet die JSON-Dateien und pusht sie in den `main`-Branch. GitHub Pages deployed daraufhin automatisch die aktuellen Daten.

Für den Wetter-Abruf muss ein `OPENWEATHER_API_KEY` als Repository-Secret hinterlegt sein.

## GitHub Pages einrichten (einmalig)

1. Repository-Einstellungen → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / `(root)`
4. Speichern → Seite ist unter `https://marcokitzmann.github.io/wo-segelt-marco/` erreichbar

## Lokale Entwicklung

```bash
python -m http.server 8080
# → http://localhost:8080
```

## Scraper manuell ausführen

```bash
pip install -r requirements.txt
python -m playwright install chromium --with-deps
python scripts/scrape.py
```

Optionale Umgebungsvariablen:

| Variable              | Beschreibung                                      |
|-----------------------|---------------------------------------------------|
| `OPENWEATHER_API_KEY` | API-Key für Wetterdaten (OpenWeatherMap One Call) |
| `SCRAPE_DEBUG`        | `1` für ausführliche Ausgabe des Seiteninhalts    |
