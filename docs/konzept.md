# Konzept: Kategorien, Aktionen, Entscheidungen

## Die Grundidee: zwei Dimensionen, nicht eine

Der übliche Fehler beim Aufräumen von Mail ist, für jedes Thema einen Ordner anzulegen.
Nach ein paar Monaten hat man vierzig Ordner, und jede Mail kostet eine Entscheidung
„wohin damit?". Genau daran schlafen solche Systeme ein.

Deshalb hier zwei getrennte Dimensionen:

| | Frage | Wirkung |
|---|---|---|
| **Kategorie** | Worum geht es? | Steuert den Vorschlag, gliedert den Bericht |
| **Aktion** | Was passiert damit? | Bestimmt den Ordner |

Die Kategorie erzeugt **keinen** Ordner. Sie sorgt dafür, dass eine Mail mit
„Nebenkostenabrechnung" anders behandelt wird als ein Newsletter – aber abgelegt wird
nach dem, was zu tun ist.

Das deckt sich mit dem, was sich in der Praxis bewährt hat: wenige Ordner, höchstens
eine Ebene Verschachtelung, handlungsorientiert statt themenorientiert – und im Übrigen
auf die Suche vertrauen statt auf die Ablage.

## Die Kategorien

| Kategorie | Was hineingehört |
|---|---|
| `geschaeftlich` | Beruflich: Mandanten, Kollegen, Projekte, Termine |
| `immobilien` | Objekte, Verwaltung, Makler, Mieter, Handwerker, Energie |
| `investment` | Beteiligungen, Depots, Fonds, Reportings, Kapitalanlage |
| `finanzen` | Bank, Versicherung, Steuer, Rechnungen, Verträge, Behörden |
| `persoenlich` | Familie, Freunde, Privates |
| `benachrichtigung` | Automatisches: Bestellungen, Versand, Logins, Systemmeldungen |
| `newsletter` | Massenversand: Werbung, Verteiler, Magazine |
| `spam` | Unerwünscht oder betrügerisch |
| `unklar` | Nicht sicher einzuordnen – deine Entscheidung |

`finanzen` war in deiner Aufzählung nicht dabei, gehört aber dazu: Rechnungen,
Versicherungen und Steuerpost sind weder Immobilie noch Investment, machen aber einen
großen Teil der Post aus und haben eine eigene Aufbewahrungslogik.

## Die Aktionen

| Aktion | Bedeutung | Landet in |
|---|---|---|
| `handeln` | Braucht eine Antwort oder eine Aufgabe von dir | `Triage/1 Handeln` |
| `wartet` | Du hast geliefert, wartest auf Antwort | `Triage/2 Wartet` |
| `lesen` | Interessant, nicht dringend | `Triage/3 Lesen` |
| `archivieren` | Aufheben zum Nachschlagen, nichts zu tun | `Archive` |
| `loeschen` | Weg damit | `Papierkorb` |
| `spam` | Unerwünscht | `Junk` |
| `behalten` | Bleibt im Posteingang | – |
| `pruefen` | Bleibt liegen, du entscheidest | – |

Das sind die vier Wege, die du genannt hast – löschen, bearbeiten, ablegen,
archivieren – plus zwei Rückfallpositionen für Fälle, in denen die Automatik nichts
entscheiden soll.

Drei Triage-Ordner, ein Archiv, Papierkorb und Junk. Mehr nicht. Das Archiv bekommt
optional eine Ebene (`Archive/Immobilien`, `Archive/Investment`, `Archive/Finanzen`),
weil du diese Bereiche getrennt durchsuchen willst.

## Wie entschieden wird

Die Regeln in `config/regeln.json` werden von oben nach unten geprüft, die erste
passende gewinnt. Passt keine, greift der Standard – und der ist `pruefen`:
**im Zweifel wird nichts angefasst.**

Der wichtigste Mechanismus ist das **Alter**. Dieselbe Mail wird unterschiedlich
behandelt, je nachdem wie lange sie liegt:

| Alter | Direkt an dich, kein Massenversand | Massenversand |
|---|---|---|
| bis 14 Tage | `handeln` | `lesen` |
| 14–30 Tage | bleibt liegen (`pruefen`) | `lesen` |
| ab 30 Tage | **`pruefen` – wird dir vorgelegt** | – |
| ab 45 Tage, nie geöffnet | – | `loeschen` |
| ab 120 Tage | – | `loeschen` |

Der wichtige Punkt in dieser Tabelle: **Echte Mail, die direkt an dich ging, wird nie
automatisch weggeräumt.** Sie landet in `pruefen` und damit in der Entscheidungsliste
des Berichts. Das ist bewusst die konservative Einstellung – automatisch behandelt
werden nur Massenversand, Benachrichtigungen und eindeutig thematische Post.

Weil der Backlog wochenweise abgearbeitet wird, bleibt diese Liste handhabbar: Sie
umfasst immer nur eine Woche, nicht den ganzen Rückstand. In der Praxis sind das
etwa 50–70 Mails pro Backlog-Woche, bei denen du entscheidest – gegenüber rund 75 %,
die das Regelwerk allein erledigt.

Wenn dir das mit der Zeit zu kleinteilig wird: In `config/regeln.json` die Regel
*„Direkt an mich, älter als ein Monat"* von `pruefen` auf `archivieren` stellen. Dann
wandert sie stumm ins Archiv – durchsuchbar, aber ohne deine Durchsicht.

Nur in Kopie (CC) gesetzte Mail wird ab 21 Tagen archiviert, ohne Vorlage. Sie war
nicht an dich adressiert, also auch nicht zur Bearbeitung gedacht.

## Die Sicherheitsnetze

Beim Aufräumen eines Backlogs ist die einzig wirklich teure Fehlentscheidung, etwas
Wichtiges zu löschen. Dagegen liegen vier Schichten:

1. **Nichts wird endgültig gelöscht.** `loeschen` heißt: ab in den Papierkorb. Der
   Papierkorb wird von diesem Werkzeug nie geleert. Alles ist wiederherstellbar,
   solange dein Mailanbieter es vorhält (iCloud: 30 Tage).
2. **Markiertes ist tabu.** Jede Mail mit Fahne in Apple Mail wird nie gelöscht, egal
   welche Regel greift. Sie wird dir stattdessen vorgelegt.
3. **Die Schutzliste.** Absender in `schutz` – Steuerberater, Anwalt, Notar, Finanzamt,
   Familie – werden nie gelöscht und nie als Spam einsortiert.
4. **Vorschlag vor Ausführung.** Jeder Lauf schreibt nur einen Vorschlag. Erst
   `anwenden --ja` bewegt etwas. Ohne `--ja` passiert nichts.

Wenn Schutz greift, wird die Regel nicht still übergangen – die Mail landet in
`pruefen` und taucht im Bericht auf. Du siehst also, wo die Automatik zurückgetreten
ist.

## Warum IMAP und nicht AppleScript

Beim letzten Anlauf ist Apple Mail abgestürzt. Das war kein Zufall und lag nicht an der
Menge deiner Mails.

AppleScript steuert Mail über Apple Events. Jede Abfrage und jede Änderung läuft
einzeln durch diese Brücke, und Suchvorgänge werden dabei im Client ausgewertet statt
auf dem Server. Bei großen Postfächern führt das zu Zeitüberschreitungen und
Abstürzen – ein bekanntes Verhalten, keine Fehlbedienung.

Dieses Werkzeug redet stattdessen direkt per IMAP mit dem Server:

- **Es lädt nur Kopfzeilen.** Absender, Betreff, Datum, Größe. Nie einen
  Nachrichtenrumpf, nie einen Anhang. Zehntausend Mails sind damit wenige Megabyte.
- **Es arbeitet in Blöcken.** 200 Kopfzeilen pro Abruf, 100 Verschiebungen pro Befehl,
  kurze Pause dazwischen.
- **Es begrenzt sich selbst.** Standardmäßig höchstens 800 Bewegungen pro Ausführung.
- **Die Arbeit passiert auf dem Server.** Apple Mail synchronisiert danach nur noch das
  Ergebnis.

**Praxistipp:** Für die großen Backlog-Läufe Apple Mail vorher schließen. Nicht weil es
sonst kaputtgeht, sondern weil es dann in Ruhe einmal sauber synchronisiert, statt
tausende Einzeländerungen live mitzuverfolgen.

## Der Bericht

Genau hier lag das zweite Problem beim letzten Mal: Der Output war so umfangreich, dass
er unbrauchbar wurde.

Der Bericht ist deshalb **aggregiert und in der Länge fest begrenzt**. Er zeigt Summen
nach Aktion und Kategorie, die größten Absender, die Fälle für deine Entscheidung und
ein paar Stichproben pro Aktion. Alles andere wird gezählt, nicht aufgelistet.

Ob 50 oder 50.000 Mails im Lauf stecken: Der Bericht bleibt unter 320 Zeilen. Der
vollständige Plan liegt als JSON daneben, falls du doch einmal alles sehen willst.

Eine Ausnahme von der Aggregation gibt es bewusst: die **Entscheidungsliste**. Was in
`pruefen` landet, wird einzeln aufgeführt – bis zu 60 Mails mit Datum, Absender und
Betreff. Das ist deine Arbeitsliste, nicht Statistik. Über `bericht_max_pruefen` in
`config/konten.json` einstellbar.

## Quellen

- [Email Triage for Fast-Paced Professionals – Mailbird](https://www.getmailbird.com/email-triage-professionals-productivity/)
- [How to Handle Email Backlog After Vacation – Mailbird](https://www.getmailbird.com/handle-email-backlog-after-vacation/)
- [Email triage: Sort faster and respond smarter – Fyxer](https://www.fyxer.com/blog/email-triage)
- [What is email triage – Superhuman](https://blog.superhuman.com/email-triage/)
- [The best way to organize email folders – Fyxer](https://www.fyxer.com/blog/best-way-to-organize-email-folders)
- [The Ideal Email Folder Structure – The Sweet Setup](https://thesweetsetup.com/the-ideal-email-folder-structure/)
- [AppleScript-Grenzen bei großen Postfächern – apple-mail-mcp #234](https://github.com/sweetrb/apple-mail-mcp/issues/234)
- [iCloud Mail server settings – Apple Support](https://support.apple.com/en-us/102525)
