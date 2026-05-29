#!/usr/bin/env bash
# Scraper + Git-Push fuer den Raspberry Pi
# Cronjob-Beispiel (jede Stunde, 10 min nach der vollen Stunde):
#   10 * * * * /home/pi/wo-segelt-marco/scripts/run_and_push.sh >> /home/pi/logs/scraper.log 2>&1

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_DIR/scripts/scrape.py"
LOG_PREFIX="[$(date -u '+%Y-%m-%dT%H:%MZ')]"

echo "$LOG_PREFIX === Scraper-Lauf gestartet ==="

# Aktuellen Stand holen
cd "$REPO_DIR"
git pull --ff-only

# Python-Umgebung aktivieren falls vorhanden
if [ -f "$REPO_DIR/.venv/bin/activate" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi

# Umgebungsvariablen aus .env laden falls dotenv nicht installiert
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

# Scraper ausfuehren
python "$SCRIPT"

# Daten committen und pushen
git add data/position.json data/history.json
[ -f "$REPO_DIR/data/weather.json" ] && git add data/weather.json || true

if git diff --staged --quiet; then
    echo "$LOG_PREFIX Keine Aenderungen – nichts zu committen."
else
    git commit -m "data: Schiffsposition + Wetter $(date -u '+%Y-%m-%dT%H:%MZ')"
    git push origin main
    echo "$LOG_PREFIX Daten gepusht."
fi

echo "$LOG_PREFIX === Scraper-Lauf beendet ==="
