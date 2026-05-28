'use strict';

let map, shipMarker, shipIconEl, pendingMapUpdate;

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

// ── Karte initialisieren ─────────────────────────────────────────────────────
function initMap() {
  map = new maplibregl.Map({
    container: 'map',
    style: 'https://tiles.openfreemap.org/styles/bright',
    center: [25, 71],   // [lng, lat]
    zoom: 4,
  });
  map.once('load', () => {
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

    if (shipMarker) {
      shipMarker.setLngLat(lngLat);
      if (shipIconEl) shipIconEl.style.transform = `rotate(${pos.course ?? 0}deg)`;
      shipMarker.getPopup().setHTML(popupHtml);
    } else {
      const el = document.createElement('div');
      el.className = 'ship-marker-wrapper';
      const pulse = document.createElement('div');
      pulse.className = 'ship-pulse';
      shipIconEl = document.createElement('span');
      shipIconEl.className = 'ship-marker';
      shipIconEl.style.transform = `rotate(${pos.course ?? 0}deg)`;
      shipIconEl.textContent = '▲';
      el.appendChild(pulse);
      el.appendChild(shipIconEl);

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
    if (w.wind_gust != null) windStr += ` (Böen ${w.wind_gust.toFixed(1)} m/s)`;
    set('w-wind', windStr);
  } else {
    set('w-wind', null);
  }

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
  if (btn) btn.textContent = '⟳ Lädt…';

  try {
    const [pos, history, cfg, weather] = await Promise.all([
      getJSON('data/position.json'),
      getJSON('data/history.json').catch(() => []),
      getJSON('config.json').catch(() => ({})),
      getJSON('data/weather.json').catch(() => null),
    ]);

    set('v-lat',      fmtCoord(pos.latitude,  'lat'));
    set('v-lon',      fmtCoord(pos.longitude, 'lon'));
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

    const sailing = cfg.marco_sailing === true;
    document.getElementById('marco-sailing').classList.toggle('hidden', !sailing);
    document.getElementById('marco-shore').classList.toggle('hidden', sailing);

    updateMap(pos, history);
    updateWeather(weather);

  } catch (err) {
    console.error('Ladefehler:', err);
    document.getElementById('last-updated').textContent =
      'Fehler beim Laden – Konsole prüfen';
  } finally {
    if (btn) btn.textContent = '↻ Aktualisieren';
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

// ── Start ────────────────────────────────────────────────────────────────────
initMap();
loadData();

document.getElementById('refresh-btn').addEventListener('click', loadData);
document.getElementById('burger-btn').addEventListener('click', toggleSidebar);
document.getElementById('sidebar-overlay').addEventListener('click', toggleSidebar);
document.getElementById('sidebar-close').addEventListener('click', toggleSidebar);
document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// Automatisch jede Stunde neu laden
setInterval(loadData, 60 * 60 * 1000);
