# Wo segelt Marco? 🚢

Verfolgt die Position der **Roald Amundsen** (MMSI 211215170) auf einer interaktiven Karte.  
Quelle: [marinetraffic.live](https://marinetraffic.live/vessels/roald-amundsen-position/211215170/)

## Live-Seite

→ **https://marcokitzmann.github.io/wo-segelt-marco/**

## Features

- Karte mit aktueller Schiffsposition und historischer Route (letzten 30 Tage)
- Anzeige von Position, Geschwindigkeit, Kurs, Abfahrts-/Zielhafen, ATD & ETA
- Automatisches Daten-Update jede Stunde per GitHub Action
- „Marco ist an Bord"-Schalter

## Marco-Schalter

In `config.json` den Wert setzen:

```json
{ "marco_sailing": true }   ← Marco ist an Bord
{ "marco_sailing": false }  ← Marco ist an Land
```

Datei committen & pushen – die Seite zeigt sofort das passende Banner.

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
pip install playwright
playwright install chromium --with-deps
python scripts/scrape.py
```
