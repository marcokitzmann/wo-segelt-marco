'use strict';

let map, shipMarker, trackLine;

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
  map = L.map('map', { center: [71, 25], zoom: 4 });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution:
      '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
      '© <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(map);
}

// ── Schiff-Icon mit Kursrotation ─────────────────────────────────────────────
function shipIcon(course) {
  const angle = course ?? 0;
  return L.divIcon({
    className: '',
    html: `<span class="ship-marker" style="transform:rotate(${angle}deg)">▲</span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -16],
  });
}

// ── Karte aktualisieren ──────────────────────────────────────────────────────
function updateMap(pos, history) {
  if (pos.latitude == null || pos.longitude == null) {
    document.getElementById('no-data-overlay').classList.remove('hidden');
    return;
  }
  document.getElementById('no-data-overlay').classList.add('hidden');

  const latlng = [pos.latitude, pos.longitude];

  // Historische Route
  if (history.length > 1) {
    const points = history.map(p => [p.lat, p.lon]);
    if (trackLine) {
      trackLine.setLatLngs(points);
    } else {
      trackLine = L.polyline(points, {
        color: '#38bdf8',
        weight: 2,
        opacity: 0.55,
        dashArray: '5 6',
      }).addTo(map);
    }
  }

  // Schiffs-Marker
  if (shipMarker) {
    shipMarker.setLatLng(latlng);
    shipMarker.setIcon(shipIcon(pos.course));
  } else {
    shipMarker = L.marker(latlng, { icon: shipIcon(pos.course) }).addTo(map);
    map.setView(latlng, 7);
  }

  const speedStr  = pos.speed  != null ? `${pos.speed} kn`  : '';
  const courseStr = pos.course != null ? `${pos.course}°`   : '';
  const navLine   = [speedStr, courseStr].filter(Boolean).join(' · ');

  shipMarker.bindPopup(
    `<strong>Roald Amundsen</strong><br>` +
    `${fmtCoord(pos.latitude, 'lat')} / ${fmtCoord(pos.longitude, 'lon')}` +
    (navLine ? `<br>${navLine}` : '')
  );
}

// ── DOM-Helfer ───────────────────────────────────────────────────────────────
function set(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || '—';
}

// ── Daten laden und anzeigen ─────────────────────────────────────────────────
async function loadData() {
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.textContent = '⟳ Lädt…';

  try {
    const [pos, history, cfg] = await Promise.all([
      getJSON('data/position.json'),
      getJSON('data/history.json').catch(() => []),
      getJSON('config.json').catch(() => ({})),
    ]);

    // Sidebar befüllen
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

    // Marco-Banner
    const sailing = cfg.marco_sailing === true;
    document.getElementById('marco-sailing').classList.toggle('hidden', !sailing);
    document.getElementById('marco-shore').classList.toggle('hidden', sailing);

    updateMap(pos, history);

  } catch (err) {
    console.error('Ladefehler:', err);
    document.getElementById('last-updated').textContent =
      'Fehler beim Laden – Konsole prüfen';
  } finally {
    if (btn) btn.textContent = '↻ Aktualisieren';
  }
}

// ── Start ────────────────────────────────────────────────────────────────────
initMap();
loadData();

// Automatisch jede Stunde neu laden
setInterval(loadData, 60 * 60 * 1000);
