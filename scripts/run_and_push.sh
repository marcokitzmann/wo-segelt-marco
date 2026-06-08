#!/usr/bin/env bash
# Scraper + Git-Push fuer den Raspberry Pi
# Cronjob-Beispiel (jede Stunde, 10 min nach der vollen Stunde):
#   10 * * * * /home/pi/wo-segelt-marco/scripts/run_and_push.sh >> /home/pi/logs/scraper.log 2>&1

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_DIR/scripts/scrape.py"
LOG_PREFIX="[$(date -u '+%Y-%m-%dT%H:%MZ')]"

echo "$LOG_PREFIX === Scraper-Lauf gestartet ==="

# Remote-Stand holen und lokalen Branch rebasen (verhindert Merge-Commits
# und klappt auch wenn Remote neue Commits hat, die lokal fehlen)
cd "$REPO_DIR"
git fetch origin
git rebase origin/main

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

    # Robuster Push: bei Ablehnung Remote-Commits rebasen und erneut versuchen
    push_ok=false
    for attempt in 1 2 3; do
        if git push origin main; then
            push_ok=true
            break
        fi
        echo "$LOG_PREFIX Push fehlgeschlagen (Versuch $attempt/3) – hole Remote-Aenderungen..."
        git fetch origin
        git rebase origin/main
    done

    if [ "$push_ok" = false ]; then
        echo "$LOG_PREFIX FEHLER: Push nach 3 Versuchen nicht erfolgreich." >&2
        exit 1
    fi

    echo "$LOG_PREFIX Daten gepusht."
fi

echo "$LOG_PREFIX === Scraper-Lauf beendet ==="
