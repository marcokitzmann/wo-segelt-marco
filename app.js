'use strict';

let map, shipMarker, shipIconEl, shipCourseLineEl, pendingMapUpdate, activeMapStyle;

const DAY_STYLE   = 'https://tiles.openfreemap.org/styles/bright';
const NIGHT_STYLE = 'https://tiles.openfreemap.org/styles/dark';

function getMapStyle() {
  const h = new Date().getHours();
  return (h >= 6 && h < 22) ? DAY_STYLE : NIGHT_STYLE;
}

// Cache-bust: neue Minute → neue Datei-Version
function bust() {
  return `?v=${Math.floor(Date.now() / 60_000)}`;
}

async function getJSON(path) {
  const res = await fetch(path + bust());
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

// ── Koordinaten-Formatierung ─────────────────────────────────────────────────
function fmtCoord(val, type) {
  if (val == null) return '—';
  const abs = Math.abs(val).toFixed(5);
  const dir = type === 'lat'
    ? (val >= 0 ? 'N' : 'S')
    : (val >= 0 ? 'E' : 'W');
  return `${abs}° ${dir}`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('de-DE', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
      timeZone: 'UTC',
    }) + ' UTC';
  } catch { return iso; }
}

// ── Datumsparser: "05/26/2026, 03:59 PM" oder "26.05.2026, 15:59" ──────────
function parsePosDate(s) {
  if (!s) return null;

  // Format: MM/DD/YYYY, HH:MM AM/PM
  const mUS = s.match(/(\d{2})\/(\d{2})\/(\d{4}),\s*(\d{1,2}):(\d{2})\s*(AM|PM)/i);
  if (mUS) {
    let [, mo, dd, yyyy, hh, min, ap] = mUS;
    hh = parseInt(hh);
    if (ap.toUpperCase() === 'PM' && hh !== 12) hh += 12;
    if (ap.toUpperCase() === 'AM' && hh === 12) hh = 0;
    return new Date(Date.UTC(+yyyy, +mo - 1, +dd, hh, +min));
  }

  // Format: DD.MM.YYYY, HH:MM (24h)
  const mDE = s.match(/(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{1,2}):(\d{2})/);
  if (mDE) {
    const [, dd, mo, yyyy, hh, min] = mDE;
    return new Date(Date.UTC(+yyyy, +mo - 1, +dd, +hh, +min));
  }

  return null;
}

// ── Reise-Fortschrittsbalken ─────────────────────────────────────────────────
function updateVoyageBar(pos) {
  const bar = document.getElementById('voyage-bar');
  if (!pos.departure_port || !pos.destination_port) {
    bar.classList.add('hidden');
    return;
  }

  let pct = null;

  // Zeitbasierte Berechnung via ATD → ETA (zuverlässiger als gescrapte Werte)
  const atd = parsePosDate(pos.atd);
  const eta = parsePosDate(pos.eta);
  if (atd && eta && eta > atd) {
    pct = Math.min(100, Math.max(0, (Date.now() - atd) / (eta - atd) * 100));
  } else if (pos.route_progress != null) {
    // Fallback: gescrapter Wert, falls Zeitdaten fehlen
    pct = pos.route_progress;
  }

  if (pct == null) {
    bar.classList.add('hidden');
    return;
  }

  const pctStr = pct.toFixed(1);
  set('vb-dep', pos.departure_port);
  set('vb-dst', pos.destination_port);
  document.getElementById('vb-fill').style.width = `${pctStr}%`;
  set('vb-pct', `${pctStr} %`);
  bar.classList.remove('hidden');
}

// ── Schiffs-Marker-Zustand aktualisieren ─────────────────────────────────────
function applyMarkerState(course, lineHeight, icon) {
  shipIconEl.parentElement.style.transform = `rotate(${course ?? 0}deg)`;
  shipIconEl.textContent = icon;
  shipCourseLineEl.style.height = `${lineHeight}px`;
}

// ── Karte initialisieren ─────────────────────────────────────────────────────
function initMap() {
  activeMapStyle = getMapStyle();
  map = new maplibregl.Map({
    container: 'map',
    style: activeMapStyle,
    center: [25, 71],   // [lng, lat]
    zoom: 4,
    attributionControl: false,
  });
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  const _missingImgCanvas = document.createElement('canvas');
  _missingImgCanvas.width = _missingImgCanvas.height = 11;
  const _missingImgCtx = _missingImgCanvas.getContext('2d');
  _missingImgCtx.beginPath();
  _missingImgCtx.arc(5.5, 5.5, 4.5, 0, Math.PI * 2);
  _missingImgCtx.fillStyle = '#888';
  _missingImgCtx.fill();
  const _missingImgData = _missingImgCtx.getImageData(0, 0, 11, 11);
  map.on('styleimagemissing', (e) => { if (!map.hasImage(e.id)) map.addImage(e.id, _missingImgData); });
  map.once('load', () => {
    document.querySelector('.maplibregl-ctrl-attrib')
      ?.classList.remove('maplibregl-compact-show');
    if (pendingMapUpdate) { pendingMapUpdate(); pendingMapUpdate = null; }
  });
}

// ── Karte aktualisieren ──────────────────────────────────────────────────────
function updateMap(pos, history) {
  if (pos.latitude == null || pos.longitude == null) {
    document.getElementById('no-data-overlay').classList.remove('hidden');
    return;
  }
  document.getElementById('no-data-overlay').classList.add('hidden');

  const lngLat = [pos.longitude, pos.latitude];  // MapLibre: [lng, lat]
  const apply = () => {
    // Historische Route
    const cutoff = Date.now() - 8 * 24 * 60 * 60 * 1000;
    const recentHistory = history.filter(p => !p.ts || new Date(p.ts).getTime() >= cutoff);
    if (recentHistory.length > 1) {
      const coords = recentHistory.map(p => [p.lon, p.lat]);
      const geojson = {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords },
      };
      if (map.getSource('track')) {
        map.getSource('track').setData(geojson);
      } else {
        map.addSource('track', { type: 'geojson', data: geojson });
        map.addLayer({
          id: 'track',
          type: 'line',
          source: 'track',
          paint: {
            'line-color': '#f97316',
            'line-width': 2.5,
            'line-opacity': 0.75,
            'line-dasharray': [2, 3],
          },
        });
      }
    }

    // Schiffs-Marker
    const speedStr  = pos.speed  != null ? `${pos.speed} kn`  : '';
    const courseStr = pos.course != null ? `${pos.course}°`   : '';
    const navLine   = [speedStr, courseStr].filter(Boolean).join(' · ');
    const popupHtml =
      `<strong>Roald Amundsen</strong><br>` +
      `${fmtCoord(pos.latitude, 'lat')} / ${fmtCoord(pos.longitude, 'lon')}` +
      (navLine ? `<br>${navLine}` : '');

    const speedKn = pos.speed ?? 0;
    const lineHeight = speedKn > 0 ? Math.round(Math.min(speedKn / 12, 1) * 50) : 0;
    const markerIcon = speedKn > 0 ? '▲' : '●';

    if (shipMarker) {
      shipMarker.setLngLat(lngLat);
      applyMarkerState(pos.course, lineHeight, markerIcon);
      shipMarker.getPopup().setHTML(popupHtml);
    } else {
      const el = document.createElement('div');
      el.className = 'ship-marker-wrapper';
      const pulse = document.createElement('div');
      pulse.className = 'ship-pulse';
      const rotator = document.createElement('div');
      rotator.className = 'ship-rotator';
      shipCourseLineEl = document.createElement('div');
      shipCourseLineEl.className = 'ship-course-line';
      shipIconEl = document.createElement('span');
      shipIconEl.className = 'ship-marker';
      rotator.appendChild(shipCourseLineEl);
      rotator.appendChild(shipIconEl);
      el.appendChild(pulse);
      el.appendChild(rotator);
      applyMarkerState(pos.course, lineHeight, markerIcon);

      const popup = new maplibregl.Popup({ offset: 16 }).setHTML(popupHtml);
      shipMarker = new maplibregl.Marker({ element: el })
        .setLngLat(lngLat)
        .setPopup(popup)
        .addTo(map);
      map.flyTo({ center: lngLat, zoom: 8 });
    }
  };

  if (map.loaded()) {
    apply();
  } else {
    pendingMapUpdate = apply;
  }
}

// ── DOM-Helfer ───────────────────────────────────────────────────────────────
function set(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || '—';
}

// ── Wetter anzeigen ──────────────────────────────────────────────────────────
function updateWeather(w) {
  const section = document.getElementById('weather-section');
  if (!w || w.temp == null) {
    if (section) section.classList.add('weather-unavailable');
    return;
  }
  if (section) section.classList.remove('weather-unavailable');

  const iconEl = document.getElementById('w-icon');
  if (iconEl && w.icon) {
    iconEl.src = `https://openweathermap.org/img/wn/${w.icon}@2x.png`;
    iconEl.alt = w.description || '';
  }

  set('w-temp',   `${Math.round(w.temp)} °C`);
  set('w-desc',   w.description ?? null);
  set('w-feels',  w.feels_like != null ? `${Math.round(w.feels_like)} °C` : null);
  set('w-clouds', w.clouds     != null ? `${w.clouds} %` : null);

  if (w.wind_speed != null) {
    let windStr = `${w.wind_speed.toFixed(1)} m/s`;
    if (w.wind_dir) windStr += ` ${w.wind_dir}`;
    set('w-wind', windStr);
  } else {
    set('w-wind', null);
  }
  set('w-gust', w.wind_gust != null ? `${w.wind_gust.toFixed(1)} m/s` : null);

  set('w-rain', w.rain_1h != null ? `${w.rain_1h.toFixed(1)} mm/h` : 'kein Regen');

  if (w.visibility != null) {
    const km = (w.visibility / 1000).toFixed(1);
    set('w-visibility', `${km} km`);
  } else {
    set('w-visibility', null);
  }
}

// ── Daten laden und anzeigen ─────────────────────────────────────────────────
async function loadData() {
  const btn = document.getElementById('refresh-btn');
  if (btn?.disabled) return;
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Lädt…'; }

  try {
    const [pos, history, cfg, weather] = await Promise.all([
      getJSON('data/position.json'),
      getJSON('data/history.json').catch(() => []),
      getJSON('config.json').catch(() => ({})),
      getJSON('data/weather.json').catch(() => null),
    ]);

    set('v-pos', `${fmtCoord(pos.latitude, 'lat')}, ${fmtCoord(pos.longitude, 'lon')}`);
    set('v-speed',    pos.speed  != null ? `${pos.speed} kn`  : null);
    set('v-course',   pos.course != null ? `${pos.course}°`   : null);
    set('v-status',   pos.status);
    set('v-dep-port', pos.departure_port);
    set('v-atd',      pos.atd);
    set('v-dst-port', pos.destination_port);
    set('v-eta',      pos.eta);

    document.getElementById('last-updated').textContent =
      pos.last_updated
        ? `Aktualisiert: ${fmtDate(pos.last_updated)}`
        : 'Noch keine Positionsdaten';

    const today = new Date().toISOString().slice(0, 10);
    const sailing = cfg.next_trip_start && cfg.next_trip_end
      && today >= cfg.next_trip_start && today <= cfg.next_trip_end;
    document.getElementById('marco-sailing').classList.toggle('hidden', !sailing);
    document.getElementById('marco-shore').classList.toggle('hidden', sailing);
    document.getElementById('sidebar-avatar').src =
      sailing ? 'images/bobblehead-marco.jpg' : 'images/bobblehead-home.jpg';

    updateVoyageBar(pos);
    updateMap(pos, history);
    updateWeather(weather);

  } catch (err) {
    console.error('Ladefehler:', err);
    document.getElementById('last-updated').textContent =
      'Fehler beim Laden – Konsole prüfen';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Aktualisieren'; }
  }
}

// ── Tab-Navigation ───────────────────────────────────────────────────────────
function switchTab(pageId) {
  document.querySelectorAll('.sidebar-page').forEach(p => p.classList.add('hidden'));
  document.getElementById(pageId).classList.remove('hidden');
  document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === pageId);
  });
}

function toggleSidebar() {
  const open = document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('visible', open);
}

// ── Tagesmeldung RSS-Feed ────────────────────────────────────────────────────
async function loadRssFeed() {
  const FEED_URL = 'https://www.sailtraining.de/category/tagesmeldungen-de/feed/';

  try {
    const box = document.getElementById('rss-box');
    const res = await fetch(`https://corsproxy.io/?${encodeURIComponent(FEED_URL)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const xml = await res.text();

    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const item = doc.querySelector('item');
    if (!item) throw new Error('Kein RSS-Item gefunden');

    const title = item.querySelector('title')?.textContent?.trim();
    const link  = item.querySelector('link')?.textContent?.trim()
               || item.querySelector('guid')?.textContent?.trim();
    const desc  = item.querySelector('description')?.textContent || '';
    const tmp   = document.createElement('div');
    tmp.innerHTML = desc;
    const text  = (tmp.textContent || tmp.innerText || '').trim();

    if (!title) throw new Error('Kein Titel im Feed');

    const href = link || FEED_URL;
    const titleEl = document.getElementById('rss-title');
    titleEl.textContent = title;
    titleEl.href = href;
    document.getElementById('rss-link').href = href;
    set('rss-excerpt', text);
    box.classList.remove('hidden');
  } catch (err) {
    console.warn('RSS-Feed konnte nicht geladen werden:', err);
  }
}

// ── Start ────────────────────────────────────────────────────────────────────
initMap();
loadData();
loadRssFeed();

document.getElementById('refresh-btn').addEventListener('click', () => { loadData(); loadRssFeed(); });

const infoBtn   = document.getElementById('info-btn');
const infoPopup = document.getElementById('info-popup');

infoBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  const open = infoPopup.classList.toggle('hidden') === false;
  infoBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
});

document.addEventListener('click', (e) => {
  if (!infoPopup.classList.contains('hidden') && !infoPopup.contains(e.target)) {
    infoPopup.classList.add('hidden');
    infoBtn.setAttribute('aria-expanded', 'false');
  }
});
document.getElementById('locate-btn').addEventListener('click', () => {
  if (shipMarker) map.flyTo({ center: shipMarker.getLngLat(), zoom: 8 });
});
document.getElementById('burger-btn').addEventListener('click', toggleSidebar);
document.getElementById('sidebar-overlay').addEventListener('click', toggleSidebar);
document.getElementById('sidebar-close').addEventListener('click', toggleSidebar);
document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// Automatisch jede Stunde neu laden — ggf. Map-Style wechseln
setInterval(() => {
  const newStyle = getMapStyle();
  if (newStyle !== activeMapStyle) {
    activeMapStyle = newStyle;
    map.setStyle(newStyle);
    map.once('styledata', loadData);
  } else {
    loadData();
  }
  loadRssFeed();
}, 60 * 60 * 1000);
