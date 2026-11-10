# Wo segelt Marco? ⛵

<p align="center">
  <img src="images/bobblehead-marco.jpg" alt="Marco Bobblehead" width="300" style="border-radius: 12px;" />
</p>

Verfolgt die Position des Traditionssegelschiffs **Roald Amundsen** (MMSI 211215170) auf einer interaktiven Karte.
Datenquelle: AIS-Datenstrom von [aisstream.io](https://aisstream.io) (WebSocket)

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
- Automatisches Daten-Update **jede Stunde** per AIS (aisstream.io)
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
│   ├── history.json        # Positionshistorie (max. 720 Einträge, Karte zeigt 8 Tage)
│   └── weather.json        # Wetterdaten an letzter Position
├── images/
│   └── bobblehead-marco.jpg
├── scripts/
│   ├── fetch_position.py   # AIS-Abruf (aisstream.io) + Wetter
│   └── run_and_push.sh     # Cronjob-Wrapper: Abruf, Commit, Push
├── requirements.txt
└── .github/workflows/
    └── update-position.yml # GitHub Action: manueller Fallback
```

## Daten-Update

`scripts/fetch_position.py` verbindet sich per WebSocket mit aisstream.io, filtert auf die MMSI der Roald Amundsen und wartet bis zu 10 Minuten auf AIS-Meldungen:

- **PositionReport** → Position, Geschwindigkeit, Kurs, Navigationsstatus
- **ShipStaticData** → Zielhafen und ETA (nach Empfang einer Position wird noch max. 2 Minuten darauf gewartet)

AIS liefert keinen Abfahrtshafen. Ändert sich das Ziel, wird das bisherige Ziel als Abfahrtshafen und der Zeitpunkt als ATD übernommen.

Empfängt das Skript im Zeitfenster keine Meldung (z. B. auf offener See außerhalb der Reichweite terrestrischer AIS-Stationen), bleiben Position und Historie unverändert. Positionen, die eine unrealistische Geschwindigkeit (> 25 kn) gegenüber dem letzten Historienpunkt erfordern würden, werden verworfen.

Die regelmäßige Aktualisierung läuft per **Cronjob** über `scripts/run_and_push.sh` (stündlich). Das Skript committet die JSON-Dateien direkt in den `main`-Branch; GitHub Pages deployed daraufhin automatisch die aktuellen Daten.

Der GitHub Actions Workflow (`update-position.yml`) dient als **manueller Fallback** und kann über die GitHub-Oberfläche gestartet werden. Dafür müssen `AISSTREAM_API_KEY` und `OPENWEATHER_API_KEY` als Repository-Secrets hinterlegt sein.

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

## Abruf manuell ausführen

```bash
pip install -r requirements.txt
python scripts/fetch_position.py
```

Umgebungsvariablen (oder `.env`):

| Variable              | Beschreibung                                               |
|-----------------------|------------------------------------------------------------|
| `AISSTREAM_API_KEY`   | **Pflicht.** API-Key von [aisstream.io](https://aisstream.io) |
| `OPENWEATHER_API_KEY` | API-Key für Wetterdaten (OpenWeatherMap One Call)          |
| `AIS_LISTEN_SECONDS`  | Maximale Wartezeit auf AIS-Meldungen (Standard: `600`)     |
| `AIS_DEBUG`           | `1` gibt jede empfangene AIS-Meldung aus                   |