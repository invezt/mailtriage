# Sicherungen

Beim Aufräumen eines Backlogs gibt es genau eine wirklich teure Fehlentscheidung:
etwas Wichtiges unwiederbringlich zu verlieren. Alles andere ist ärgerlich, aber
reparabel.

Deshalb liegen hier mehrere Schichten übereinander. Die ersten sechs sind **fest
verdrahtet** – sie stehen im Code, nicht in der Konfiguration, und lassen sich durch
keine Regel und keine Einstellung aushebeln.

## Was das Werkzeug grundsätzlich nicht kann

### 1. Es versendet nie eine Mail

Es gibt keine Versandfunktion. Kein SMTP, kein Antworten, kein Weiterleiten, keine
Entwürfe. Das Werkzeug kann Nachrichten lesen und zwischen Ordnern verschieben – mehr
nicht.

### 2. Es löscht nie endgültig

`loeschen` heißt ausschließlich: **in den Papierkorb verschieben**. Der Papierkorb wird
nie geleert. Was dort liegt, kannst du in Apple Mail markieren und zurückschieben –
oder liegen lassen, bis dein Anbieter es automatisch entfernt (iCloud: nach 30 Tagen).

Es gibt keinen Codepfad, der Mail wirklich löscht. Kein `EXPUNGE` über einen ganzen
Ordner, kein Löschen von Ordnern.

### 3. Es lädt nie Nachrichteninhalte

Abgerufen werden nur Kopfzeilen: Absender, Betreff, Datum, Größe, Flags. Nie ein
Nachrichtenrumpf, nie ein Anhang. Das ist gleichzeitig der Grund, warum große Läufe
schnell sind – und heißt nebenbei, dass der Inhalt deiner Mail den Server nie verlässt.

### 4. Frische Post wird nie automatisch gelöscht

Harte Untergrenze: **nichts unter 30 Tagen** wandert automatisch in den Papierkorb, egal
welche Regel greift. Auch eine Regel, die ausdrücklich „alles löschen" sagt, kommt an
dieser Grenze nicht vorbei.

Einzige Ausnahme: offensichtlicher Massenversand darf auch frisch in den Spam-Ordner –
sonst wäre die Spam-Erkennung wirkungslos. Echte, direkt an dich adressierte Post nie.

Einstellbar über `mindestalter_loeschen_tage` – nach oben. Nach unten begrenzt der Code.

### 5. Postausgang, Entwürfe, Papierkorb und Spam bleiben unberührt

Diese Ordner werden nie als Quelle gelesen und damit nie umsortiert. Auch dann nicht,
wenn jemand sie versehentlich in `quell_ordner` einträgt – der Lauf bricht dann mit
einer Erklärung ab. Erkannt werden auch die deutschen und die Exchange-Varianten
(*Gesendete Objekte*, *Gelöschte Elemente*, *Junk-E-Mail* …).

### 6. Ordnerwechsel löscht nichts

Ein Detail mit echter Sprengkraft: Das IMAP-Kommando `CLOSE` entfernt beim Schließen
eines Ordners **alle dort mit `\Deleted` markierten Nachrichten endgültig** – auch die,
die *du* in Apple Mail markiert und noch gar nicht loswerden wolltest. Das Werkzeug
benutzt deshalb durchgängig `UNSELECT`, das dasselbe tut, ohne zu löschen. Kann ein
Server das nicht, wird der Ordner vorher auf Nur-Lesen umgestellt – dann ist auch
`CLOSE` harmlos.

## Was du selbst steuerst

### Vorschlag vor Ausführung

Jeder Lauf schreibt nur einen Vorschlag. **Ohne `--ja` passiert nichts.**

```bash
python3 -m mailtriage anwenden        # zeigt, was passieren würde
python3 -m mailtriage anwenden --ja   # führt es aus
```

### Im Zweifel nichts

Passt keine Regel, bleibt die Mail liegen und wird dir vorgelegt. Und echte, direkt an
dich adressierte Post wird grundsätzlich nie automatisch weggeräumt – nur Massenversand,
Benachrichtigungen und eindeutig thematische Mail.

### Markiertes ist tabu

Jede Mail mit Fahne in Apple Mail wird nie gelöscht, egal welche Regel greift. Das ist
dein manuelles Veto: markieren, und das Werkzeug fasst sie nicht an.

### Schutzliste

Absender, bei denen nie etwas schiefgehen darf – Steuerberater, Anwalt, Notar, Bank,
Finanzamt. In `config/regeln.json`:

```json
"schutz": {
  "kommentar": "Nie löschen, nie als Spam",
  "von_domain": ["elster.de", "meine-kanzlei.de", "meine-bank.de"],
  "von_adresse": ["steuerberater@kanzlei.de"]
}
```

Greift ein Schutz, wird die Regel nicht still übergangen: Die Mail landet in `pruefen`
und taucht im Bericht auf. Du siehst also, wo die Automatik zurückgetreten ist.

### Notbremse gegen kaputte Regeln

Der wahrscheinlichste Weg, echten Schaden anzurichten, ist ein zu weit gefasster
Regeleintrag – ein Betreff-Muster, das versehentlich auf alles passt.

Dagegen prüft das Werkzeug jeden Plan vor der Ausführung: Sollen **über 90 %** aller
Nachrichten weggeräumt werden, und geht davon **über 80 % auf eine einzige Regel**
zurück, bricht es ab und nennt die Regel.

Wichtig ist die zweite Bedingung. Eine alte Woche, die zu 100 % aus Newslettern besteht,
darf komplett weggeräumt werden – da sind mehrere Regeln beteiligt, das ist normal.
Verdächtig ist nur, wenn *eine* Regel alles abräumt.

Ist der Vorschlag wirklich richtig: `--notbremse-loesen`.

### Eingewöhnungsmodus

Für die ersten Wochen, bis du dem Regelwerk traust:

```bash
python3 -m mailtriage nachmittags --ohne-loeschen
```

Dann wird nichts gelöscht und nichts als Spam einsortiert. Alles Destruktive landet in
der Prüfliste. Du siehst also, *was* das Regelwerk löschen würde, ohne dass es passiert.

### Konten nur beobachten

Ein Postfach lässt sich auf Nur-Lesen stellen – es wird gescannt und berichtet, aber nie
verändert. Sinnvoll, um dem System erst auf dem privaten Konto zu vertrauen, bevor das
geschäftliche drankommt:

```json
{ "name": "firma", "nur_lesen": true, ... }
```

## Wenn doch etwas schiefgeht

### Rückgängig machen

Jeder ausgeführte Lauf lässt sich zurückdrehen:

```bash
python3 -m mailtriage rueckgaengig        # zeigt, was zurückkäme
python3 -m mailtriage rueckgaengig --ja   # holt es zurück
```

Das funktioniert auch dann noch, wenn der Server den Nachrichten beim Verschieben neue
Kennungen gegeben hat: Wiedergefunden werden sie über die **Message-ID**, die jede Mail
dauerhaft mit sich trägt. Was sich nicht wiederfinden lässt – etwa weil du es
zwischenzeitlich selbst verschoben hast – wird gezählt und gemeldet, nicht verschwiegen.

### Von Hand

Der vollständige Plan jedes Laufs liegt als JSON in `runs/`. Dort steht für jede
Nachricht, woher sie kam und wohin sie ging. Und alles liegt in normalen Ordnern, die du
in Apple Mail öffnen, markieren und zurückschieben kannst.

## Warum das auch morgen noch stimmt

Die Zusagen 1, 2, 3 und 6 sind in `tests/test_guards.py` als Test hinterlegt, der den
**Quelltext selbst liest**: kein SMTP-Import, kein `expunge()`, kein Abruf ganzer
Nachrichten, kein `CLOSE` auf einem schreibbaren Ordner.

Das ist ungewöhnlich für einen Test, aber hier der Punkt: Eine Zusage in der
Dokumentation ist nur so lange etwas wert, wie sie beim nächsten Umbau nicht versehentlich
gebrochen wird. Ein Test, der den Code liest, fängt das ab.

```bash
python3 -m unittest discover -s tests
```
