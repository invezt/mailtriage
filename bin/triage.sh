#!/bin/bash
# Wrapper fuer launchd und fuer die Hand.
#
#   bin/triage.sh morgens
#   bin/triage.sh nachmittags
#
# Scannt und schreibt den Bericht. Veraendert nichts - das Anwenden
# passiert bewusst nur von Hand.
set -uo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODUS="${1:-morgens}"
PROTOKOLL="$WURZEL/runs/protokoll.log"
mkdir -p "$WURZEL/runs"

cd "$WURZEL" || exit 1

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')  $MODUS ==="
  /usr/bin/env python3 -m mailtriage "$MODUS" --leise
  ERGEBNIS=$?
  echo "=== Ende (Code $ERGEBNIS) ==="
} >> "$PROTOKOLL" 2>&1
ERGEBNIS=${ERGEBNIS:-1}

# Kurze Rueckmeldung auf den Schreibtisch, damit man weiss, dass etwas bereitliegt.
LETZTER=$(ls -t "$WURZEL"/runs/*.md 2>/dev/null | head -1)
if [ -n "$LETZTER" ] && [ "$ERGEBNIS" -eq 0 ]; then
  ZEILE=$(grep -m1 'Nachrichten:' "$LETZTER" | sed 's/[-*]//g; s/^ *//')
  /usr/bin/osascript -e "display notification \"$ZEILE\" with title \"E-Mail-Triage: $MODUS\" subtitle \"Bericht liegt bereit\"" 2>/dev/null
else
  /usr/bin/osascript -e "display notification \"Siehe runs/protokoll.log\" with title \"E-Mail-Triage: $MODUS\" subtitle \"Lauf fehlgeschlagen\"" 2>/dev/null
fi

exit "$ERGEBNIS"
