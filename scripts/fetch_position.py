#!/usr/bin/env python3
"""
Ermittelt die Position der Roald Amundsen ueber den AIS-Datenstrom von
aisstream.io (WebSocket) und schreibt data/position.json und data/history.json.
Holt zusaetzlich Wetterdaten von OpenWeatherMap (data/weather.json).

Umgebungsvariablen (oder .env):
  AISSTREAM_API_KEY    API-Key von https://aisstream.io (Pflicht)
  OPENWEATHER_API_KEY  API-Key fuer Wetterdaten (optional)
  AIS_LISTEN_SECONDS   Maximale Wartezeit auf AIS-Meldungen (Standard: 600)
  AIS_DEBUG            1 = jede empfangene Meldung ausgeben
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import random

import requests
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

VESSEL_NAME = "Roald Amundsen"
MMSI = "211215170"
AIS_URL = "wss://stream.aisstream.io/v0/stream"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_HISTORY = 720                 # ~30 Tage bei stuendlichem Lauf
LISTEN_SECONDS = int(os.getenv("AIS_LISTEN_SECONDS", "600"))
STATIC_GRACE_SECONDS = 120        # nach Position noch so lange auf Ziel/ETA warten
MAX_CONNECT_ATTEMPTS = 3
DEBUG = os.getenv("AIS_DEBUG", "").lower() in ("1", "true", "yes")

# Roald Amundsen faehrt max. ~16 kn; Schwelle mit Sicherheitsabstand
MAX_PLAUSIBLE_SPEED_KN = 25.0

# AIS-Navigationsstatus (ITU-R M.1371)
NAV_STATUS = {
    0: "In Fahrt (Motor)",
    1: "Vor Anker",
    2: "Manövrierunfähig",
    3: "Eingeschränkt manövrierfähig",
    4: "Tiefgangbehindert",
    5: "Festgemacht",
    6: "Auf Grund",
    7: "Fischerei",
    8: "Unter Segeln",
}


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _get(obj: dict, *keys):
    """Erster vorhandener Wert unter mehreren moeglichen Schluesselnamen."""
    for k in keys:
        if obj.get(k) is not None:
            return obj[k]
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(max(0.0, a)))


def _parse_time_utc(raw) -> datetime | None:
    """aisstream liefert z. B. '2026-11-10 14:03:12.123456789 +0000 UTC'."""
    if not raw:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", str(raw))
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00")


def _fmt_de(dt: datetime) -> str:
    """Format, das app.js (parsePosDate) versteht: 'DD.MM.YYYY, HH:MM'."""
    return dt.strftime("%d.%m.%Y, %H:%M")


def _parse_eta(eta: dict | None, now: datetime) -> str | None:
    """AIS-ETA hat kein Jahr: naechstes passendes Datum ab heute waehlen."""
    if not isinstance(eta, dict):
        return None
    month, day = eta.get("Month") or 0, eta.get("Day") or 0
    hour, minute = eta.get("Hour", 24), eta.get("Minute", 60)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if not (0 <= hour <= 23):
        hour = 0
    if not (0 <= minute <= 59):
        minute = 0
    for year in (now.year, now.year + 1):
        try:
            dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        # ETA darf hoechstens ~30 Tage in der Vergangenheit liegen
        if (now - dt).days <= 30:
            return _fmt_de(dt)
    return None


def _clean_destination(raw) -> str | None:
    if not raw:
        return None
    dest = re.sub(r"[@\s]+", " ", str(raw)).strip()
    return dest or None


# ── AIS-Meldungen auswerten ───────────────────────────────────────────────────

def parse_position(msg: dict) -> dict | None:
    """PositionReport / StandardClassBPositionReport -> Positionsdaten."""
    mtype = msg.get("MessageType")
    body = (msg.get("Message") or {}).get(mtype) or {}
    meta = msg.get("MetaData") or {}

    lat = _get(body, "Latitude")
    lon = _get(body, "Longitude")
    if lat is None or lon is None:
        lat = _get(meta, "latitude", "Latitude")
        lon = _get(meta, "longitude", "Longitude")
    if lat is None or lon is None:
        return None
    # 91 / 181 = "nicht verfuegbar"; 0/0 ist ebenfalls ungueltig
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    if body.get("Valid") is False:
        return None

    sog = body.get("Sog")
    cog = body.get("Cog")
    nav = body.get("NavigationalStatus")
    ts = _parse_time_utc(_get(meta, "time_utc", "TimeUtc")) or datetime.now(timezone.utc)

    return {
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "speed": round(sog, 1) if sog is not None and sog < 102.2 else None,
        "course": round(cog, 1) if cog is not None and 0 <= cog < 360 else None,
        "status": NAV_STATUS.get(nav),
        "position_time": ts.isoformat(),
    }


def parse_static(msg: dict) -> dict:
    """ShipStaticData -> Ziel und ETA."""
    body = (msg.get("Message") or {}).get("ShipStaticData") or {}
    return {
        "destination_port": _clean_destination(body.get("Destination")),
        "eta": _parse_eta(body.get("Eta"), datetime.now(timezone.utc)),
    }


class AisConnectionError(Exception):
    """aisstream war nicht erreichbar oder hat die Subscription abgelehnt."""


async def listen() -> tuple[dict | None, dict | None]:
    api_key = os.getenv("AISSTREAM_API_KEY")
    if not api_key:
        sys.exit("FEHLER: AISSTREAM_API_KEY ist nicht gesetzt.")

    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": [MMSI],
        "FilterMessageTypes": [
            "PositionReport",
            "StandardClassBPositionReport",
            "ShipStaticData",
        ],
    }

    position: dict | None = None
    static: dict | None = None
    confirmed = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LISTEN_SECONDS

    print(f"Verbinde mit {AIS_URL}, warte max. {LISTEN_SECONDS} s auf MMSI {MMSI} ...", flush=True)
    for attempt in range(1, MAX_CONNECT_ATTEMPTS + 1):
        try:
            async with connect(AIS_URL, compression="deflate", open_timeout=20) as ws:
                await ws.send(json.dumps(subscription))
                while not (position and static):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                    if DEBUG:
                        print(json.dumps(msg, ensure_ascii=False))
                    if "error" in msg:
                        raise RuntimeError(f"aisstream meldet: {msg['error']}")

                    mtype = msg.get("MessageType")
                    if mtype == "SubscriptionConfirmation":
                        confirmed = True
                        print("Subscription bestätigt.", flush=True)
                    elif mtype in ("PositionReport", "StandardClassBPositionReport"):
                        parsed = parse_position(msg)
                        if parsed:
                            position = parsed
                            print(f"Position empfangen: {parsed}", flush=True)
                            # Nach der ersten Position nur noch kurz auf Ziel/ETA warten
                            deadline = min(deadline, loop.time() + STATIC_GRACE_SECONDS)
                    elif mtype == "ShipStaticData":
                        static = parse_static(msg)
                        print(f"Statische Daten empfangen: {static}", flush=True)
            break   # Zeitfenster regulaer beendet
        except (OSError, WebSocketException, RuntimeError) as exc:
            hint = "" if confirmed else " (Subscription nicht bestätigt - API-Key prüfen)"
            print(f"Verbindungsfehler (Versuch {attempt}/{MAX_CONNECT_ATTEMPTS}): {exc!r}{hint}",
                  file=sys.stderr, flush=True)
            if position or attempt == MAX_CONNECT_ATTEMPTS or deadline - loop.time() < 30:
                if not position and not confirmed:
                    raise AisConnectionError(str(exc)) from exc
                break
            await asyncio.sleep(min(5 * 2 ** attempt, 60) + random.uniform(0, 3))

    return position, static


# ── Plausibilitaet, History, Wetter ──────────────────────────────────────────

def is_plausible(pos: dict, last: dict) -> bool:
    if not last or last.get("lat") is None or last.get("lon") is None:
        return True
    dist_km = _haversine_km(last["lat"], last["lon"], pos["latitude"], pos["longitude"])
    hours = 2.0
    try:
        t_new = datetime.fromisoformat(pos["position_time"])
        t_old = datetime.fromisoformat(last["ts"].replace("Z", "+00:00"))
        hours = max(0.25, (t_new - t_old).total_seconds() / 3600)
    except Exception:
        pass
    implied_kn = dist_km / 1.852 / hours
    if implied_kn > MAX_PLAUSIBLE_SPEED_KN:
        print(
            f"WARNUNG: Unplausible Position ({pos['latitude']}, {pos['longitude']}) - "
            f"{dist_km:.1f} km in {hours:.1f} h = {implied_kn:.1f} kn. Verworfen.",
            file=sys.stderr,
        )
        return False
    return True


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


_WIND_DIRS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]


def fetch_weather(lat: float, lon: float) -> dict | None:
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        print("Kein OPENWEATHER_API_KEY - Wetter übersprungen.")
        return None
    url = (
        "https://api.openweathermap.org/data/3.0/onecall"
        f"?lat={lat}&lon={lon}&units=metric&lang=de"
        f"&exclude=minutely,hourly,daily,alerts&appid={api_key}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        print(f"Wetter-Abruf fehlgeschlagen: {exc}", file=sys.stderr)
        return None

    cur = raw.get("current", {})
    weather = (cur.get("weather") or [{}])[0]
    deg = cur.get("wind_deg")
    return {
        "lat":          raw.get("lat"),
        "lon":          raw.get("lon"),
        "timezone":     raw.get("timezone"),
        "temp":         cur.get("temp"),
        "feels_like":   cur.get("feels_like"),
        "clouds":       cur.get("clouds"),
        "visibility":   cur.get("visibility"),
        "wind_speed":   cur.get("wind_speed"),
        "wind_gust":    cur.get("wind_gust"),
        "wind_deg":     deg,
        "wind_dir":     _WIND_DIRS[round(deg / 45) % 8] if deg is not None else None,
        "rain_1h":      (cur.get("rain") or {}).get("1h"),
        "description":  weather.get("description"),
        "icon":         weather.get("icon"),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pos_file = DATA_DIR / "position.json"
    hist_file = DATA_DIR / "history.json"

    old = load_json(pos_file, {})
    history = load_json(hist_file, [])
    if not isinstance(history, list):
        history = []

    try:
        position, static = asyncio.run(listen())
    except AisConnectionError as exc:
        sys.exit(f"FEHLER: Keine Verbindung zu aisstream.io: {exc}")

    new = dict(old)
    new["vessel"] = VESSEL_NAME
    new["mmsi"] = MMSI
    new.pop("route_progress", None)   # Feld des alten Scrapers, per AIS nicht verfuegbar
    changed = False

    if position and is_plausible(position, history[-1] if history else {}):
        new.update({k: position[k] for k in ("latitude", "longitude", "speed", "course", "status")})
        new["last_updated"] = position["position_time"]
        changed = True

        last = history[-1] if history else {}
        if (last.get("lat"), last.get("lon")) != (position["latitude"], position["longitude"]):
            history.append({
                "lat": position["latitude"],
                "lon": position["longitude"],
                "speed": position["speed"],
                "course": position["course"],
                "ts": position["position_time"],
            })
            history = history[-MAX_HISTORY:]
            write_json(hist_file, history)
            print(f"History: {len(history)} Einträge.")
    elif not position:
        print("Keine Positionsmeldung empfangen - Position bleibt unverändert.")

    if static and static.get("destination_port"):
        dest = static["destination_port"]
        old_dest = old.get("destination_port")
        if old_dest and old_dest != dest:
            # Neues Ziel = neue Reise: altes Ziel wird Abfahrtshafen
            new["departure_port"] = old_dest
            new["atd"] = _fmt_de(datetime.now(timezone.utc))
        new["destination_port"] = dest
        new["eta"] = static.get("eta")
        changed = True

    if changed:
        write_json(pos_file, new)
        print("position.json geschrieben.")

    # Wetter an der (letzten bekannten) Position bei jedem Lauf aktualisieren
    if new.get("latitude") is not None and new.get("longitude") is not None:
        weather = fetch_weather(new["latitude"], new["longitude"])
        if weather:
            write_json(DATA_DIR / "weather.json", weather)
            print("weather.json geschrieben.")

    print("Fertig.")


if __name__ == "__main__":
    main()
