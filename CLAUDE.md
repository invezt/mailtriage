# mailtriage

Tägliche E-Mail-Triage über mehrere IMAP-Postfächer. Läuft auf dem Mac des
Nutzers, mit Zugriff auf dessen echte Mail.

**Die Sprache hier ist Deutsch.** Benutzerausgaben, Doku und Commit-Nachrichten
auf Deutsch; Bezeichner im Code auf Englisch, Kommentare auf Deutsch.

## Was das Werkzeug tut

Zwei feste Sessions pro Tag (10:00 und 16:00) plus wochenweises Zurückarbeiten
eines jahrealten Rückstands. Jeder Lauf erzeugt nur einen **Vorschlag**; erst
ein ausdrückliches `--ja` bewegt Nachrichten.

```
python3 -m mailtriage morgens                 # neue Post seit dem letzten Lauf
python3 -m mailtriage nachmittags             # neue Post + eine Woche Rückstand
python3 -m mailtriage backlog --wochen N      # nur Rückstand, N Wochen
python3 -m mailtriage anwenden [--ja]         # Vorschlag ausführen
python3 -m mailtriage rueckgaengig [--ja]     # letzten Lauf zurückdrehen
python3 -m mailtriage status                  # Fortschritt im Rückstand
python3 -m mailtriage einrichten [--anlegen]  # Verbindung prüfen, Ordner anlegen
python3 -m mailtriage passwoerter             # Passwörter in den Schlüsselbund
```

Scan-Befehle kennen `--seit JJJJ-MM-TT`, `--ohne-loeschen` und `--konto NAME`.

## Regeln für diese Sitzung

**Niemals ohne ausdrückliche Zustimmung in diesem Gespräch ausführen:**
`anwenden --ja` und `rueckgaengig --ja`. Beide verändern echte Postfächer. Erst
den Trockenlauf zeigen, den Bericht zusammenfassen, dann fragen.

**Niemals nach Passwörtern fragen und nie eines entgegennehmen.** Sie liegen im
macOS-Schlüsselbund. Fehlt eines, führe `python3 -m mailtriage passwoerter` aus:
Der Befehl übernimmt zuerst das Passwort, das Apple Mail ohnehin hinterlegt hat
(macOS fragt per Fenster nach der Freigabe), und öffnet sonst ein natives
Passwortfenster. Die Eingabe geht direkt in den Schlüsselbund und wird nie
ausgegeben — sie taucht also auch in diesem Gespräch nicht auf. Das ist so
gewollt: bitte nicht umgehen, indem du das Passwort erfragst oder ausliest.

**Niemals `config/konten.json`, `config/regeln.json`, `runs/` oder `state/`
committen.** Sie enthalten echte Adressen und Betreffzeilen und stehen in
`.gitignore`.

**Berichte nicht vollständig ins Gespräch kopieren.** Sie sind bewusst
aggregiert; zusammenfassen, nicht ausschütten. Das Sprengen des Outputs war
genau das Problem, das dieses Werkzeug lösen soll.

## Vor jedem Commit

```
python3 -m unittest discover -s tests
python3 -m pyflakes mailtriage/ tests/
```

Beides muss sauber sein. Nur Standardbibliothek verwenden — keine neuen
Abhängigkeiten, das Werkzeug soll mit dem Python laufen, das macOS mitbringt.

## Aufbau

| Datei | Zweck |
|---|---|
| `mailtriage/mailbox.py` | IMAP: Kopfzeilen lesen, in Blöcken verschieben |
| `mailtriage/rules.py` | Regelwerk, Schutzliste |
| `mailtriage/guards.py` | Harte Sicherungen, **nicht** abschaltbar |
| `mailtriage/planner.py` | Scannen, Vorschlag schreiben |
| `mailtriage/applier.py` | Vorschlag ausführen, Rückgängig |
| `mailtriage/report.py` | Aggregierter Bericht mit Zeilenlimit |
| `mailtriage/wizard.py` | Einrichtungsassistent (`start`) |
| `tests/imap_testserver.py` | Echter IMAP-Server für die Tests |

## Was niemals gebrochen werden darf

`mailtriage/guards.py` und `tests/test_guards.py` halten Zusagen fest, die der
Nutzer ausdrücklich verlangt hat. Sie sind durch Tests gesichert, die den
Quelltext lesen:

- Es wird **nie** eine Mail versendet (kein SMTP).
- Es wird **nie** endgültig gelöscht — `loeschen` heißt Papierkorb.
- Es werden **nie** Nachrichteninhalte geladen, nur Kopfzeilen.
- Ordnerwechsel benutzt `UNSELECT`, nie `CLOSE` auf einem schreibbaren Ordner
  (`CLOSE` würde vom Nutzer markierte Mails endgültig entfernen).

Wenn eine Änderung einen dieser Tests rot macht, ist die Änderung falsch —
nicht der Test.

## Details

- [docs/konzept.md](docs/konzept.md) — Kategorien, Entscheidungslogik
- [docs/sicherungen.md](docs/sicherungen.md) — was nicht passieren kann
- [docs/zeitplan.md](docs/zeitplan.md) — 10:00/16:00, Rückstandsrechnung
- [docs/einrichtung.md](docs/einrichtung.md) — Einrichtung Schritt für Schritt
