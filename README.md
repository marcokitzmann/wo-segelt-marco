# Wo segelt Marco? ⛵

<p align="center">
  <img src="images/bobblehead-marco.jpg" alt="Marco Bobblehead" width="300" style="border-radius: 12px;" />
</p>

Verfolgt die Position des Traditionssegelschiffs **Roald Amundsen** (MMSI 211215170) auf einer interaktiven Karte.
Datenquelle: [marinetraffic.live](https://marinetraffic.live/vessels/roald-amundsen-position/211215170/)

## Live-Seite

→ **https://marcokitzmann.github.io/wo-segelt-marco/**


## Über die Roald Amundsen

Die *Roald Amundsen* ist ein als Brigg getakeltes Traditionsschiff, das von einer Besatzung aus Stamm-Crew und Trainees ganzjährig gefahren wird.

Wenn du mehr über die *Roald Amundsen* erfahren willst oder selbst mitsegeln möchtest: [www.sailtraining.de](https://www.sailtraining.de)

## Features

- Interaktive Karte (MapLibre GL) mit aktueller Schiffsposition und historischer Route (letzte 8 Tage)
- Kursrichtungslinie am Schiffsmarker zeigt die aktuelle Fahrtrichtung
- Sidebar mit zwei Tabs:
  - **Status** – Marco-an-Bord-Banner (konfigurierbar per `config.json`) inkl. letzter Tagesmeldung (RSS)
  - **Schiff & Wetter** – Position, Geschwindigkeit, Kurs, Navigationsstatus, Abfahrts-/Zielhafen, ATD & ETA
- Reisefortschrittsbalken (zeitbasierte Berechnung via ATD → ETA)
- Aktuelles Wetter an der letzten Position (Temperatur, Wind, Bewölkung, Niederschlag, Sichtweite) via OpenWeatherMap
- Info-Button `?` in der Sidebar mit Hinweis auf Echtzeit-Tracking
- Automatisches Daten-Update **jede Stunde** (täglich ~24 Scraper-Läufe)
- Manueller Trigger des Workflows mit optionaler Debug-Ausgabe möglich
- Responsives Design, funktioniert auf Desktop und Mobilgeräten

## On-Board-Status

In `config.json` den Reisezeitraum setzen:

```json
{
  "next_trip_start": "2026-06-01",
  "next_trip_end":   "2026-06-07"
}
```

Liegt das aktuelle Datum im Zeitraum, zeigt die Seite „Marco ist an Bord!". Datei committen & pushen – die Seite aktualisiert sich sofort.

## Projektstruktur

```
wo-segelt-marco/
├── index.html              # Hauptseite (MapLibre GL, zweispaltig mit Sidebar)
├── style.css               # Styling
├── app.js                  # Kartenlogik, Daten laden, UI
├── config.json             # Marco-an-Bord-Schalter (next_trip_start / next_trip_end)
├── data/
│   ├── position.json       # Aktuelle Schiffsposition (stündlich aktualisiert)
│   ├── history.json        # Positionshistorie (max. 192 Einträge ≈ 8 Tage)
│   └── weather.json        # Wetterdaten an letzter Position
├── images/
│   └── bobblehead-marco.jpg
├── scripts/
│   └── scrape.py           # Playwright-Scraper (marinetraffic.live)
├── requirements.txt
└── .github/workflows/
    └── scrape.yml          # GitHub Action: manueller Fallback-Scraper
```

## Daten-Update

Das automatische Scraping läuft als **Cronjob auf einem Raspberry Pi** (stündlich). Der Scraper committet die JSON-Dateien direkt in den `main`-Branch; GitHub Pages deployed daraufhin automatisch die aktuellen Daten.

Der GitHub Actions Workflow (`scrape.yml`) dient als **manueller Fallback** und kann über die GitHub-Oberfläche gestartet werden – z. B. wenn der Pi nicht erreichbar ist. Optional kann dabei Debug-Ausgabe aktiviert werden.

Für den Wetter-Abruf im manuellen Workflow muss ein `OPENWEATHER_API_KEY` als Repository-Secret hinterlegt sein.

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