#!/usr/bin/env python3
"""
Scrapes vessel position from marinetraffic.live and saves to data/position.json
and data/history.json. Optionally fetches weather data from OpenWeatherMap
One Call API 3.0 and saves to data/weather.json.

Requires playwright (pip install playwright &&
python -m playwright install chromium --with-deps).
Set OPENWEATHER_API_KEY in environment or .env file.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import requests

URL = "https://marinetraffic.live/vessels/roald-amundsen-position/211215170/"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_HISTORY = 720  # ~30 days at 1 h interval
DEBUG = os.getenv("SCRAPE_DEBUG", "").lower() in ("1", "true", "yes")

MERGE_KEYS = (
    "latitude", "longitude", "speed", "course", "status",
    "departure_port", "atd", "destination_port", "eta",
)


# ── Coordinate parsing ────────────────────────────────────────────────────────

def _check(val: float, kind: str) -> float | None:
    if kind == "lat" and -90 <= val <= 90:
        return round(val, 6)
    if kind == "lon" and -180 <= val <= 180:
        return round(val, 6)
    return None


def parse_coord(raw: str, kind: str) -> float | None:
    """Convert various coordinate formats to decimal degrees."""
    if not raw:
        return None
    s = raw.strip()

    # "69.2053° N" / "69.2053 N" / "69.2053N"
    m = re.search(r"(\d{1,3}\.\d+)\s*°?\s*([NSEWnsew])", s)
    if m:
        val = float(m.group(1))
        if m.group(2).upper() in ("S", "W"):
            val = -val
        return _check(val, kind)

    # "69°12.30'N" / "69°12'18\"N"
    m = re.search(r"(\d{1,3})[°\s]\s*(\d{1,2})[.\'](\d*)[\'\"]\s*([NSEWnsew])", s)
    if m:
        deg = int(m.group(1))
        minutes = int(m.group(2))
        sec_frac = float("0." + m.group(3)) if m.group(3) else 0.0
        val = deg + (minutes + sec_frac) / 60
        if m.group(4).upper() in ("S", "W"):
            val = -val
        return _check(val, kind)

    # plain decimal (possibly negative)
    m = re.search(r"(-?\d{1,3}\.\d+)", s)
    if m:
        return _check(float(m.group(1)), kind)

    return None


def parse_float(raw: str) -> float | None:
    m = re.search(r"(\d+\.?\d*)", raw or "")
    return float(m.group(1)) if m else None


def parse_position(raw: str) -> tuple[float | None, float | None]:
    """Parse combined 'lat, lon' string like '55.70, 12.69'."""
    m = re.search(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", (raw or "").strip())
    if not m:
        return None, None
    return _check(float(m.group(1)), "lat"), _check(float(m.group(2)), "lon")


# ── Field mapping ─────────────────────────────────────────────────────────────

_LAT_KEYS      = ("latitude", "lat", "breite", "breitengrad")
_LON_KEYS      = ("longitude", "lon", "lng", "längengrad", "laengengrad")
_POS_KEYS      = ("position", "pos", "coordinates", "koordinaten")
_SPD_KEYS      = ("speed", "speed (sog)", "sog", "geschwindigkeit", "tempo")
_CRS_KEYS      = ("course", "course (cog)", "cog", "heading", "kurs", "hdg")
_STA_KEYS      = ("status", "nav status", "nav. status", "navigationsstatus")
_ATD_KEYS      = ("atd", "actual time of departure", "departed", "abfahrtszeit")
_ETA_KEYS      = ("eta", "estimated time of arrival", "ankunftszeit")
_DEP_PORT_KEYS = (
    "departure port", "last port", "from port", "abfahrtshafen",
    "letzter hafen", "departure", "from", "last port of call",
)
_DST_PORT_KEYS = (
    "destination", "destination port", "next port", "zielhafen",
    "to port", "to", "next port of call",
)

_EMPTY = {"", "—", "-", "n/a", "unknown"}


def _set_if_none(data: dict, key: str, val) -> None:
    """Write val into data[key] only when the current value is None."""
    if val is not None and data.get(key) is None:
        data[key] = val


def apply(data: dict, label: str, value: str) -> None:
    """Map a scraped label/value pair into the data dict."""
    if not value or value.strip().lower() in _EMPTY:
        return
    lbl = label.lower().strip().rstrip(":").strip()
    val = value.strip()

    if lbl in _POS_KEYS:
        lat, lon = parse_position(val)
        _set_if_none(data, "latitude", lat)
        _set_if_none(data, "longitude", lon)
    elif lbl in _LAT_KEYS:
        _set_if_none(data, "latitude", parse_coord(val, "lat"))
    elif lbl in _LON_KEYS:
        _set_if_none(data, "longitude", parse_coord(val, "lon"))
    elif lbl in _SPD_KEYS:
        _set_if_none(data, "speed", parse_float(val))
    elif lbl in _CRS_KEYS:
        _set_if_none(data, "course", parse_float(val))
    elif lbl in _STA_KEYS:
        _set_if_none(data, "status", val)
    elif lbl in _DEP_PORT_KEYS:
        _set_if_none(data, "departure_port", val)
    elif lbl in _ATD_KEYS:
        _set_if_none(data, "atd", val)
    elif lbl in _DST_PORT_KEYS:
        _set_if_none(data, "destination_port", val)
    elif lbl in _ETA_KEYS:
        _set_if_none(data, "eta", val)


# ── Regex fallback on raw page text ──────────────────────────────────────────

def regex_extract(data: dict, text: str) -> None:
    if data["latitude"] is None:
        # "69.2053° N / 18.9600° E" or "69.2053 N, 18.9600 E"
        m = re.search(
            r"(-?\d{1,3}\.\d{2,})\s*°?\s*([NS])\s*[/,]?\s*(-?\d{1,3}\.\d{2,})\s*°?\s*([EW])",
            text, re.IGNORECASE,
        )
        if m:
            lat = float(m.group(1)) * (-1 if m.group(2).upper() == "S" else 1)
            lon = float(m.group(3)) * (-1 if m.group(4).upper() == "W" else 1)
            _set_if_none(data, "latitude",  _check(lat, "lat"))
            _set_if_none(data, "longitude", _check(lon, "lon"))

    if data["latitude"] is None:
        lat, lon = parse_position(text)   # re.search – works anywhere in text
        _set_if_none(data, "latitude",  lat)
        _set_if_none(data, "longitude", lon)

    if data["speed"] is None:
        m = re.search(r"(?:speed|sog|tempo)[^\d]*(\d+\.?\d*)", text, re.IGNORECASE)
        if m:
            data["speed"] = float(m.group(1))

    if data["course"] is None:
        m = re.search(r"(?:course|cog|heading|kurs)[^\d]*(\d+\.?\d*)", text, re.IGNORECASE)
        if m:
            data["course"] = float(m.group(1))


# ── JSON-LD / embedded JSON helper ───────────────────────────────────────────

def _from_jsonld(data: dict, obj) -> None:
    """Recursively look for lat/lon/speed keys in a parsed JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if "latitude" in kl:
                num = float(v) if isinstance(v, (int, float)) else (
                    float(v) if isinstance(v, str) and re.fullmatch(r"-?\d+\.?\d*", v.strip()) else None
                )
                _set_if_none(data, "latitude",  _check(num, "lat") if num is not None else None)
            elif "longitude" in kl:
                num = float(v) if isinstance(v, (int, float)) else (
                    float(v) if isinstance(v, str) and re.fullmatch(r"-?\d+\.?\d*", v.strip()) else None
                )
                _set_if_none(data, "longitude", _check(num, "lon") if num is not None else None)
            elif "speed" in kl and isinstance(v, (int, float)):
                _set_if_none(data, "speed", float(v))
            else:
                _from_jsonld(data, v)
    elif isinstance(obj, list):
        for item in obj:
            _from_jsonld(data, item)


# ── Voyage section (ports, ATD, ETA) ─────────────────────────────────────────

async def scrape_voyage_section(page, data: dict) -> None:
    """Extract departure/arrival ports and times from .voyage-section."""
    section = await page.query_selector(".voyage-section")
    if not section:
        return

    voyage: dict = await section.evaluate("""(el) => {
        const out = { atd: null, eta: null, departure_port: null, destination_port: null };

        for (const block of el.querySelectorAll('div[style*="flex: 1"]')) {
            const children = block.querySelectorAll(':scope > div');
            if (children.length < 2) continue;
            const lbl = children[0].textContent.trim().toLowerCase();
            const val = children[1].textContent.trim();
            if (lbl.includes('abfahrt') || lbl.includes('atd')) out.atd = val;
            if (lbl.includes('ankunft') || lbl.includes('eta')) out.eta = val;
        }

        const ports = el.querySelectorAll('.voyage-timeline .port-info .port-code');
        if (ports[0]) out.departure_port = ports[0].textContent.trim();
        if (ports[1]) out.destination_port = ports[1].textContent.trim();

        return out;
    }""")

    for key in ("atd", "eta", "departure_port", "destination_port"):
        _set_if_none(data, key, voyage.get(key) or None)


# ── Playwright scraper ────────────────────────────────────────────────────────

async def scrape() -> dict:
    from playwright.async_api import async_playwright

    base: dict = {
        "vessel":           "Roald Amundsen",
        "mmsi":             "211215170",
        "latitude":         None,
        "longitude":        None,
        "speed":            None,
        "course":           None,
        "status":           None,
        "departure_port":   None,
        "atd":              None,
        "destination_port": None,
        "eta":              None,
        "last_updated":     datetime.now(timezone.utc).isoformat(),
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()

        print(f"→ Fetching {URL}", flush=True)
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"Navigation error: {exc}", file=sys.stderr)
            await browser.close()
            return base

        try:
            await page.wait_for_selector(
                ".ship-details-grid .detail-item, .voyage-section",
                timeout=20_000,
            )
        except Exception:
            print("Warning: expected selectors not found within timeout.", file=sys.stderr)

        body_text = await page.evaluate("document.body.innerText")
        if DEBUG:
            print("── page text (first 3000 chars) ──")
            print(body_text[:3000])
            print("──────────────────────────────────")

        data = dict(base)

        # Strategy 0: marinetraffic.live ship-details grid (.detail-label / .detail-value)
        for item in await page.query_selector_all(".ship-details-grid .detail-item"):
            try:
                lbl_el = await item.query_selector(".detail-label")
                val_el = await item.query_selector(".detail-value")
                if lbl_el and val_el:
                    apply(data, await lbl_el.inner_text(), await val_el.inner_text())
            except Exception:
                pass

        # Strategy 1: voyage section (ports, ATD, ETA)
        await scrape_voyage_section(page, data)

        # Strategy 2: table rows <td>label</td><td>value</td>
        for row in await page.query_selector_all("table tr"):
            cells = await row.query_selector_all("td, th")
            if len(cells) >= 2:
                apply(data, await cells[0].inner_text(), await cells[1].inner_text())

        # Strategy 3: definition lists <dt>label</dt><dd>value</dd>
        for dt in await page.query_selector_all("dt"):
            try:
                dd  = await page.evaluate_handle("el => el.nextElementSibling", dt)
                val = await page.evaluate("el => el ? el.innerText : ''", dd)
                apply(data, await dt.inner_text(), str(val))
            except Exception:
                pass

        # Strategy 4: generic label/value sibling divs (excluding detail-grid, handled above)
        for lbl_el in await page.query_selector_all(
            ".label, .key, .info-label, .field-label"
        ):
            try:
                sib = await page.evaluate_handle("el => el.nextElementSibling", lbl_el)
                val = await page.evaluate("el => el ? el.innerText : ''", sib)
                apply(data, await lbl_el.inner_text(), str(val))
            except Exception:
                pass

        # Strategy 5: JSON-LD structured data
        for script in await page.query_selector_all('script[type="application/ld+json"]'):
            try:
                _from_jsonld(data, json.loads(await script.inner_text()))
            except Exception:
                pass

        # Strategy 6: embedded JSON in inline script tags
        for script in await page.query_selector_all("script:not([src])"):
            try:
                src = await script.inner_text()
                for m in re.finditer(r"\{[^{}]{20,}\}", src):
                    try:
                        _from_jsonld(data, json.loads(m.group()))
                    except Exception:
                        pass
            except Exception:
                pass

        # Strategy 7: regex fallback on full body text
        regex_extract(data, body_text)

        await browser.close()

    print("── scraped data ──")
    print(json.dumps(data, indent=2))
    return data


# ── History management ────────────────────────────────────────────────────────

def update_history(pos: dict) -> None:
    path = DATA_DIR / "history.json"
    history: list = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    if pos.get("latitude") is not None and pos.get("longitude") is not None:
        entry = {
            "lat":    pos["latitude"],
            "lon":    pos["longitude"],
            "speed":  pos.get("speed"),
            "course": pos.get("course"),
            "ts":     pos.get("last_updated"),
        }
        last = history[-1] if history else {}
        if last.get("lat") != entry["lat"] or last.get("lon") != entry["lon"]:
            history.append(entry)

    history = history[-MAX_HISTORY:]
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"History: {len(history)} entries saved.")


# ── Weather fetch ─────────────────────────────────────────────────────────────

_WIND_DIRS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]


def _wind_dir_label(deg: float | None) -> str:
    if deg is None:
        return ""
    return _WIND_DIRS[round(deg / 45) % 8]


def fetch_weather(lat: float, lon: float) -> dict | None:
    """Fetch current weather from OpenWeatherMap One Call API 3.0."""
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        print("OPENWEATHER_API_KEY not set – skipping weather fetch.", file=sys.stderr)
        return None

    url = (
        f"https://api.openweathermap.org/data/3.0/onecall"
        f"?lat={lat}&lon={lon}&units=metric&lang=de"
        f"&exclude=minutely,hourly,daily,alerts&appid={api_key}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        print(f"Weather API error: {exc}", file=sys.stderr)
        return None

    d = raw.get("current") or {}
    weather = (d.get("weather") or [{}])[0]
    wind_deg = d.get("wind_deg")

    rain_1h = (d.get("rain") or {}).get("1h")

    result = {
        "lat":          raw.get("lat"),
        "lon":          raw.get("lon"),
        "timezone":     raw.get("timezone"),
        "temp":         d.get("temp"),
        "feels_like":   d.get("feels_like"),
        "clouds":       d.get("clouds"),
        "visibility":   d.get("visibility"),
        "wind_speed":   d.get("wind_speed"),
        "wind_gust":    d.get("wind_gust"),
        "wind_deg":     wind_deg,
        "wind_dir":     _wind_dir_label(wind_deg),
        "rain_1h":      rain_1h,
        "description":  weather.get("description"),
        "icon":         weather.get("icon"),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    print("── weather data ──")
    print(json.dumps(result, indent=2))
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    new_data = asyncio.run(scrape())

    pos_file = DATA_DIR / "position.json"
    if pos_file.exists():
        try:
            old = json.loads(pos_file.read_text(encoding="utf-8"))
            for key in MERGE_KEYS:
                if new_data.get(key) is None and old.get(key) is not None:
                    new_data[key] = old[key]
        except Exception:
            pass

    pos_file.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("position.json written.")

    update_history(new_data)

    # Wetterdaten nur abrufen wenn Koordinaten vorliegen
    lat, lon = new_data.get("latitude"), new_data.get("longitude")
    if lat is not None and lon is not None:
        weather = fetch_weather(lat, lon)
        if weather:
            weather_file = DATA_DIR / "weather.json"
            weather_file.write_text(
                json.dumps(weather, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print("weather.json written.")
    else:
        print("No coordinates – weather fetch skipped.")

    print("Done.")


if __name__ == "__main__":
    main()
