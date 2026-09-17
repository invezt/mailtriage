# mailtriage

Tägliche E-Mail-Triage über mehrere Postfächer – zweimal am Tag, mit einem Vorschlag
zum Prüfen statt einer Automatik, die einfach macht.

Gebaut für zwei Dinge gleichzeitig: den laufenden Tag sauber halten **und** einen über
Jahre gewachsenen Rückstand abarbeiten, ohne dass Apple Mail dabei in die Knie geht.

## In drei Sätzen

Um 10:00 und 16:00 liest das Werkzeug die neue Post – und nachmittags zusätzlich eine
Woche aus dem Rückstand, rückwärts durch die Zeit. Es schlägt für jede Mail eine
Kategorie und eine Aktion vor und schreibt einen kurzen Bericht. Du liest den Bericht,
und erst dein `--ja` bewegt etwas.

## Schnellstart

Auf dem Mac, auf dem deine Mail liegt:

```bash
git clone https://github.com/invezt/mailtriage.git ~/mailtriage
cd ~/mailtriage
python3 -m mailtriage start
```

Der Assistent fragt die Postfächer ab, legt die Passwörter im Schlüsselbund ab,
testet die Verbindung, legt die Ordner an und macht den ersten Lauf – der nur liest.
Danach:

```bash
python3 -m mailtriage anwenden        # zeigt, was passieren würde
python3 -m mailtriage anwenden --ja   # führt es aus
```

Schritt für Schritt in [docs/einrichtung.md](docs/einrichtung.md).

## Befehle

| Befehl | Was er tut |
|---|---|
| `start` | Einrichtungsassistent: Postfächer, Ordner, erster Lauf |
| `morgens` | Nur neue Post seit dem letzten Lauf |
| `nachmittags` | Neue Post **und** eine Woche Rückstand |
| `backlog --wochen N` | Nur Rückstand, N Wochen am Stück |
| `anwenden [--ja]` | Den letzten Vorschlag ausführen |
| `rueckgaengig [--ja]` | Einen ausgeführten Lauf zurückdrehen |
| `status` | Wie weit ist der Rückstand |
| `einrichten [--anlegen]` | Verbindung prüfen, Ordner anlegen |

Die Scan-Befehle kennen `--seit JJJJ-MM-TT` (ein bestimmtes Datum als Startpunkt),
`--ohne-loeschen` (Eingewöhnungsmodus) und `--wochen N` (mehrere Backlog-Wochen).
| `kategorien` | Kategorien und Aktionen anzeigen |

## Was es einordnet

**Kategorie** (worum geht es): geschäftlich · Immobilien · Investment · Finanzen ·
persönlich · Benachrichtigung · Newsletter · Spam · unklar

**Aktion** (was passiert): handeln · wartet · lesen · archivieren · löschen · Spam ·
behalten · prüfen

Die Aktion bestimmt den Ordner, die Kategorie nicht – sonst entsteht ein Ordnerwald, in
dem jede Ablage eine Entscheidung kostet. Mehr dazu in
[docs/konzept.md](docs/konzept.md).

## Warum nichts kaputtgeht

Fest verdrahtet, durch keine Regel und keine Einstellung aushebelbar:

- **Es versendet nie eine Mail.** Kein SMTP, kein Antworten, kein Weiterleiten.
- **Es löscht nie endgültig.** `loeschen` heißt Papierkorb; der wird nie geleert.
- **Es lädt nie Nachrichteninhalte.** Nur Kopfzeilen, nie ein Rumpf, nie ein Anhang.
- **Nichts unter 30 Tagen** wird automatisch gelöscht, egal welche Regel greift.
- **Postausgang, Entwürfe, Papierkorb und Spam** werden nie als Quelle gelesen.
- **Ordnerwechsel löscht nichts** – `UNSELECT` statt `CLOSE`, sonst würden von dir
  markierte Mails endgültig verschwinden.

Dazu, was du selbst steuerst:

- **Vorschlag vor Ausführung.** Ohne `--ja` passiert nichts.
- **Markiertes ist tabu.** Eine Mail mit Fahne wird nie gelöscht – dein manuelles Veto.
- **Schutzliste** für Steuerberater, Anwalt, Bank, Finanzamt.
- **Notbremse** gegen zu weit gefasste Regeln.
- **Eingewöhnungsmodus** `--ohne-loeschen` und **Nur-Lesen-Konten**.
- **Rückgängig** über die Message-ID, auch nach Neuvergabe der UIDs.

Die ersten sechs Punkte sind als Test hinterlegt, der den Quelltext selbst liest –
damit sie auch nach dem nächsten Umbau noch gelten. Details in
[docs/sicherungen.md](docs/sicherungen.md).

## Warum es Apple Mail nicht überlastet

Der übliche Weg – AppleScript gegen Mail.app – bricht bei großen Postfächern
zusammen, weil jede Abfrage einzeln über die Apple-Events-Brücke läuft und
Suchvorgänge im Client ausgewertet werden.

Dieses Werkzeug spricht direkt per IMAP mit dem Server und lädt **nur Kopfzeilen** –
nie einen Nachrichtenrumpf, nie einen Anhang. Es arbeitet in Blöcken von 200 Abrufen
bzw. 100 Verschiebungen mit Pause dazwischen und begrenzt sich auf 800 Bewegungen pro
Ausführung. Apple Mail synchronisiert danach nur noch das Ergebnis.

Auch der Bericht ist begrenzt: **unter 320 Zeilen, egal ob 50 oder 50.000 Mails** im
Lauf stecken. Summen und Stichproben statt Zeile für Zeile – einzeln aufgeführt wird
nur die Entscheidungsliste, weil das deine Arbeitsliste ist.

## Aufbau

```
mailtriage/
├── mailtriage/          Der Code (nur Python-Standardbibliothek)
│   ├── mailbox.py       IMAP: Kopfzeilen lesen, in Blöcken verschieben
│   ├── rules.py         Regelwerk und Sicherheitsnetze
│   ├── planner.py       Scannen und Vorschlag schreiben
│   ├── applier.py       Vorschlag ausführen
│   ├── report.py        Aggregierter Bericht mit Zeilenlimit
│   ├── guards.py        Harte Sicherungen, nicht abschaltbar
│   ├── wizard.py        Einrichtungsassistent
│   ├── state.py         Fortschritt im Rückstand
│   └── taxonomy.py      Kategorien und Aktionen
├── config/              Postfächer und Regeln (Beispiele im Repo)
├── docs/                Konzept, Zeitplan, Einrichtung
├── launchd/             Zeitplan für 09:45 und 15:45
├── runs/                Vorschläge und Berichte (nicht im Repo)
└── state/               Fortschritt (nicht im Repo)
```

`config/konten.json`, `config/regeln.json`, `runs/` und `state/` sind bewusst in
`.gitignore` – dort stehen echte Adressen und Betreffzeilen.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

112 Tests. Darunter ein vollständiger IMAP-Server, gegen den der echte Client über
eine echte TLS-Verbindung läuft – Attrappen allein hätten die Fehler nicht gefunden,
die dabei aufgefallen sind.

## Doku

- [Zeitplan](docs/zeitplan.md) – warum 10:00 und 16:00, wie lange der Rückstand dauert
- [Konzept](docs/konzept.md) – Kategorien, Entscheidungslogik, Sicherheitsnetze
- [Sicherungen](docs/sicherungen.md) – was nicht passieren kann, und warum
- [Einrichtung](docs/einrichtung.md) – Schritt für Schritt
