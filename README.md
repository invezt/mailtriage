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

```bash
cp config/konten.beispiel.json config/konten.json     # Postfächer eintragen
cp config/regeln.beispiel.json config/regeln.json     # Regeln anpassen

python3 -m mailtriage einrichten --anlegen            # Verbindung + Ordner
python3 -m mailtriage morgens                         # scannen (verändert nichts)
python3 -m mailtriage anwenden                        # Trockenlauf
python3 -m mailtriage anwenden --ja                   # ausführen
```

Vollständig in [docs/einrichtung.md](docs/einrichtung.md).

## Befehle

| Befehl | Was er tut |
|---|---|
| `morgens` | Nur neue Post seit dem letzten Lauf |
| `nachmittags` | Neue Post **und** eine Woche Rückstand |
| `backlog --wochen N` | Nur Rückstand, N Wochen am Stück |
| `anwenden [--ja]` | Den letzten Vorschlag ausführen |
| `status` | Wie weit ist der Rückstand |
| `einrichten [--anlegen]` | Verbindung prüfen, Ordner anlegen |
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

- **Gelöscht heißt Papierkorb.** Endgültig gelöscht wird nie, der Papierkorb nie
  geleert.
- **Markiertes ist tabu.** Eine Mail mit Fahne wird nie gelöscht.
- **Schutzliste.** Steuerberater, Anwalt, Bank, Finanzamt – nie löschen, nie Spam.
- **Vorschlag vor Ausführung.** Ohne `--ja` passiert nichts.
- **Im Zweifel nichts.** Passt keine Regel, bleibt die Mail liegen und wird vorgelegt.

## Warum es Apple Mail nicht überlastet

Der übliche Weg – AppleScript gegen Mail.app – bricht bei großen Postfächern
zusammen, weil jede Abfrage einzeln über die Apple-Events-Brücke läuft und
Suchvorgänge im Client ausgewertet werden.

Dieses Werkzeug spricht direkt per IMAP mit dem Server und lädt **nur Kopfzeilen** –
nie einen Nachrichtenrumpf, nie einen Anhang. Es arbeitet in Blöcken von 200 Abrufen
bzw. 100 Verschiebungen mit Pause dazwischen und begrenzt sich auf 800 Bewegungen pro
Ausführung. Apple Mail synchronisiert danach nur noch das Ergebnis.

Auch der Bericht ist begrenzt: **unter 220 Zeilen, egal ob 50 oder 50.000 Mails** im
Lauf stecken. Summen und Stichproben statt Zeile für Zeile.

## Aufbau

```
mailtriage/
├── mailtriage/          Der Code (nur Python-Standardbibliothek)
│   ├── mailbox.py       IMAP: Kopfzeilen lesen, in Blöcken verschieben
│   ├── rules.py         Regelwerk und Sicherheitsnetze
│   ├── planner.py       Scannen und Vorschlag schreiben
│   ├── applier.py       Vorschlag ausführen
│   ├── report.py        Aggregierter Bericht mit Zeilenlimit
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

## Doku

- [Zeitplan](docs/zeitplan.md) – warum 10:00 und 16:00, wie lange der Rückstand dauert
- [Konzept](docs/konzept.md) – Kategorien, Entscheidungslogik, Sicherheitsnetze
- [Einrichtung](docs/einrichtung.md) – Schritt für Schritt
