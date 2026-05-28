#!/usr/bin/env python3
"""
Scrapes vessel position from marinetraffic.live and saves to data/position.json
and data/history.json. Requires playwright (pip install playwright &&
playwright install chromium --with-deps).
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

URL = "https://marinetraffic.live/vessels/roald-amundsen-position/211215170/"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_HISTORY = 720  # ~30 days at 1 h interval


# ── Coordinate parsing ────────────────────────────────────────────────────────

def parse_coord(raw: str, kind: str) -> float | None:
    """Convert various coordinate formats to decimal degrees."""
    if not raw:
        return None
    s = raw.strip()

    # "69.2053° N" or "69.2053 N" or "69.2053N"
    m = re.search(r'(\d{1,3}\.\d+)\s*°?\s*([NSEWnsew])', s)
    if m:
        val = float(m.group(1))
        if m.group(2).upper() in ('S', 'W'):
            val = -val
        return _check(val, kind)

    # "69°12.30'N" or "69°12'18\"N"
    m = re.search(r'(\d{1,3})[°\s]\s*(\d{1,2})[.\'](\d*)[\'"]?\s*([NSEWnsew])', s)
    if m:
        deg = int(m.group(1))
        minutes = int(m.group(2))
        sec_frac = float('0.' + m.group(3)) if m.group(3) else 0.0
        val = deg + (minutes + sec_frac) / 60
        if m.group(4).upper() in ('S', 'W'):
            val = -val
        return _check(val, kind)

    # plain decimal (possibly negative)
    m = re.search(r'(-?\d{1,3}\.\d+)', s)
    if m:
        return _check(float(m.group(1)), kind)

    return None


def _check(val: float, kind: str) -> float | None:
    if kind == 'lat' and -90 <= val <= 90:
        return round(val, 6)
    if kind == 'lon' and -180 <= val <= 180:
        return round(val, 6)
    return None


def parse_float(raw: str) -> float | None:
    m = re.search(r'(\d+\.?\d*)', raw or '')
    return float(m.group(1)) if m else None


# ── Field mapping ─────────────────────────────────────────────────────────────

_LAT_KEYS  = ('latitude', 'lat', 'breite')
_LON_KEYS  = ('longitude', 'lon', 'lng', 'länge', 'laenge')
_SPD_KEYS  = ('speed', 'speed (sog)', 'sog', 'geschwindigkeit')
_CRS_KEYS  = ('course', 'course (cog)', 'cog', 'heading', 'kurs', 'hdg')
_STA_KEYS  = ('status', 'nav status', 'nav. status', 'navigationsstatus')
_ATD_KEYS  = ('atd', 'actual time of departure', 'departed', 'abfahrtszeit')
_ETA_KEYS  = ('eta', 'estimated time of arrival', 'ankunftszeit')

_DEP_PORT_KEYS = ('departure port', 'last port', 'from port', 'abfahrtshafen',
                  'letzter hafen', 'departure', 'from', 'last port of call')
_DST_PORT_KEYS = ('destination', 'destination port', 'next port', 'zielhafen',
                  'to port', 'to', 'next port of call')


def apply(data: dict, label: str, value: str):
    """Map a label → value pair into the data dict."""
    if not value or value.strip() in ('', '—', '-', 'N/A', 'n/a', 'unknown'):
        return
    lbl = label.lower().strip().rstrip(':').strip()
    val = value.strip()

    if lbl in _LAT_KEYS:
        data['latitude']       = parse_coord(val, 'lat') or data['latitude']
    elif lbl in _LON_KEYS:
        data['longitude']      = parse_coord(val, 'lon') or data['longitude']
    elif lbl in _SPD_KEYS:
        data['speed']          = parse_float(val) or data['speed']
    elif lbl in _CRS_KEYS:
        data['course']         = parse_float(val) or data['course']
    elif lbl in _STA_KEYS:
        data['status']         = val or data['status']
    elif lbl in _DEP_PORT_KEYS:
        data['departure_port'] = val or data['departure_port']
    elif lbl in _ATD_KEYS:
        data['atd']            = val or data['atd']
    elif lbl in _DST_PORT_KEYS:
        data['destination_port'] = val or data['destination_port']
    elif lbl in _ETA_KEYS:
        data['eta']            = val or data['eta']


# ── Regex fallback on raw page text ──────────────────────────────────────────

def regex_extract(data: dict, text: str):
    # "69.2053° N / 18.9600° E"  or  "69.2053 N, 18.9600 E"
    m = re.search(
        r'(-?\d{1,3}\.\d{2,})\s*°?\s*([NS])\s*[/,]?\s*(-?\d{1,3}\.\d{2,})\s*°?\s*([EW])',
        text, re.IGNORECASE
    )
    if m and data['latitude'] is None:
        lat = float(m.group(1)) * (-1 if m.group(2).upper() == 'S' else 1)
        lon = float(m.group(3)) * (-1 if m.group(4).upper() == 'W' else 1)
        data['latitude']  = _check(lat, 'lat')
        data['longitude'] = _check(lon, 'lon')

    if data['speed'] is None:
        m = re.search(r'(?:speed|sog)[^\d]*(\d+\.?\d*)', text, re.IGNORECASE)
        if m:
            data['speed'] = float(m.group(1))

    if data['course'] is None:
        m = re.search(r'(?:course|cog|heading|kurs)[^\d]*(\d+\.?\d*)', text, re.IGNORECASE)
        if m:
            data['course'] = float(m.group(1))


# ── Playwright scraper ────────────────────────────────────────────────────────

async def scrape() -> dict:
    from playwright.async_api import async_playwright

    base: dict = {
        'vessel': 'Roald Amundsen',
        'mmsi': '211215170',
        'latitude': None,
        'longitude': None,
        'speed': None,
        'course': None,
        'status': None,
        'departure_port': None,
        'atd': None,
        'destination_port': None,
        'eta': None,
        'last_updated': datetime.now(timezone.utc).isoformat(),
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
        )
        page = await ctx.new_page()

        print(f'→ Fetching {URL}', flush=True)
        try:
            await page.goto(URL, wait_until='domcontentloaded', timeout=60_000)
            await page.wait_for_timeout(5_000)
        except Exception as exc:
            print(f'Navigation error: {exc}', file=sys.stderr)
            await browser.close()
            return base

        # Dump first 3000 chars of body text for debugging
        body_text = await page.evaluate('document.body.innerText')
        print('── page text (first 3000 chars) ──')
        print(body_text[:3000])
        print('──────────────────────────────────')

        data = dict(base)

        # Strategy 1: table rows  (label in first cell, value in second)
        rows = await page.query_selector_all('table tr')
        for row in rows:
            cells = await row.query_selector_all('td, th')
            if len(cells) >= 2:
                lbl = (await cells[0].inner_text()).strip()
                val = (await cells[1].inner_text()).strip()
                apply(data, lbl, val)

        # Strategy 2: definition lists  <dt>label</dt><dd>value</dd>
        dts = await page.query_selector_all('dt')
        for dt in dts:
            try:
                lbl = (await dt.inner_text()).strip()
                dd  = await page.evaluate_handle(
                    'el => el.nextElementSibling', dt
                )
                val = await page.evaluate('el => el ? el.innerText : ""', dd)
                apply(data, lbl, str(val).strip())
            except Exception:
                pass

        # Strategy 3: generic key/value divs  (.label + .value, .key + .data, …)
        for pair_sel in [
            ('.label, .key, .info-label, .field-label',
             '.value, .data, .info-value, .field-value'),
        ]:
            lbls = await page.query_selector_all(pair_sel[0])
            for lbl_el in lbls:
                try:
                    lbl = (await lbl_el.inner_text()).strip()
                    sib = await page.evaluate_handle(
                        'el => el.nextElementSibling', lbl_el
                    )
                    val = await page.evaluate('el => el ? el.innerText : ""', sib)
                    apply(data, lbl, str(val).strip())
                except Exception:
                    pass

        # Strategy 4: JSON-LD structured data
        for script in await page.query_selector_all('script[type="application/ld+json"]'):
            try:
                obj = json.loads(await script.inner_text())
                _from_jsonld(data, obj)
            except Exception:
                pass

        # Strategy 5: embedded JSON in regular script tags
        for script in await page.query_selector_all('script:not([src])'):
            try:
                src = await script.inner_text()
                for m in re.finditer(r'\{[^{}]{20,}\}', src):
                    try:
                        obj = json.loads(m.group())
                        _from_jsonld(data, obj)
                    except Exception:
                        pass
            except Exception:
                pass

        # Strategy 6: regex fallback on full text
        regex_extract(data, body_text)

        await browser.close()

    print('── scraped data ──')
    print(json.dumps(data, indent=2))
    return data


def _from_jsonld(data: dict, obj):
    """Recursively look for lat/lon/speed keys in a JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if 'latitude'  in kl and isinstance(v, (int, float)) and data['latitude']  is None:
                data['latitude']  = _check(float(v), 'lat')
            elif 'longitude' in kl and isinstance(v, (int, float)) and data['longitude'] is None:
                data['longitude'] = _check(float(v), 'lon')
            elif 'speed'     in kl and isinstance(v, (int, float)) and data['speed']     is None:
                data['speed']     = float(v)
            else:
                _from_jsonld(data, v)
    elif isinstance(obj, list):
        for item in obj:
            _from_jsonld(data, item)


# ── History management ────────────────────────────────────────────────────────

def update_history(pos: dict):
    path = DATA_DIR / 'history.json'
    history: list = []
    if path.exists():
        try:
            history = json.loads(path.read_text())
        except Exception:
            history = []

    if pos.get('latitude') and pos.get('longitude'):
        entry = {
            'lat': pos['latitude'],
            'lon': pos['longitude'],
            'speed':  pos.get('speed'),
            'course': pos.get('course'),
            'ts':     pos.get('last_updated'),
        }
        # Skip exact duplicate
        if not history or (
            history[-1]['lat'] != entry['lat'] or
            history[-1]['lon'] != entry['lon']
        ):
            history.append(entry)

    history = history[-MAX_HISTORY:]
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    print(f'History: {len(history)} entries saved.')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    new_data = asyncio.run(scrape())

    # Merge with existing data: keep old values for fields we couldn't scrape
    pos_file = DATA_DIR / 'position.json'
    if pos_file.exists():
        try:
            old = json.loads(pos_file.read_text())
            for key in ('latitude', 'longitude', 'speed', 'course', 'status',
                        'departure_port', 'atd', 'destination_port', 'eta'):
                if new_data.get(key) is None and old.get(key) is not None:
                    new_data[key] = old[key]
        except Exception:
            pass

    pos_file.write_text(json.dumps(new_data, indent=2, ensure_ascii=False))
    print('position.json written.')

    update_history(new_data)
    print('Done.')


if __name__ == '__main__':
    main()
