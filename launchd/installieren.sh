#!/bin/bash
# Richtet die beiden Zeitplaene als LaunchAgents ein (10:00 und 16:00).
#
#   ./launchd/installieren.sh            einrichten
#   ./launchd/installieren.sh entfernen  wieder abschalten
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIEL="$HOME/Library/LaunchAgents"
JOBS=(de.mailtriage.morgens de.mailtriage.nachmittags)

if [ "${1:-}" = "entfernen" ]; then
  for job in "${JOBS[@]}"; do
    launchctl bootout "gui/$UID/$job" 2>/dev/null || true
    rm -f "$ZIEL/$job.plist"
    echo "entfernt: $job"
  done
  exit 0
fi

mkdir -p "$ZIEL"
for job in "${JOBS[@]}"; do
  sed "s|PFAD_ZUM_REPO|$WURZEL|g" "$WURZEL/launchd/$job.plist" > "$ZIEL/$job.plist"
  launchctl bootout "gui/$UID/$job" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$ZIEL/$job.plist"
  echo "eingerichtet: $job"
done

echo
echo "Aktive Zeitplaene:"
launchctl list | grep mailtriage || echo "  (keine - siehe runs/launchd.log)"
echo
echo "Morgens 09:45 und nachmittags 15:45 laeuft jetzt der Scan."
echo "Der Bericht liegt dann in runs/ bereit, wenn du dich um 10:00 bzw. 16:00 hinsetzt."
