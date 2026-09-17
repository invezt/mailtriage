# Einrichtung

Einmalig, dauert etwa 20 Minuten. Alles läuft auf deinem Mac; nichts davon braucht eine
Installation von Zusatzpaketen – nur das Python, das macOS mitbringt.

## 1. Repository holen

```bash
git clone https://github.com/invezt/mailtriage.git ~/mailtriage
cd ~/mailtriage
python3 --version          # 3.9 oder neuer
```

## 2. Konfiguration anlegen

```bash
cp config/konten.beispiel.json config/konten.json
cp config/regeln.beispiel.json config/regeln.json
```

Beide Dateien sind in `.gitignore` – sie enthalten deine Postfächer und Absender und
landen nie im Repository. Nur die `*.beispiel.json` sind versioniert.

## 3. App-spezifische Passwörter erzeugen

**Für iCloud ist das Pflicht.** Das normale Apple-ID-Passwort funktioniert bei IMAP
nicht – das ist der häufigste Grund für „Benutzername oder Passwort falsch".

1. [account.apple.com](https://account.apple.com) → Anmelden
2. *Anmeldung und Sicherheit* → *App-spezifische Passwörter*
3. Neues Passwort erzeugen, Name z. B. `mailtriage`
4. Das 16-stellige Passwort (`xxxx-xxxx-xxxx-xxxx`) sofort kopieren – Apple zeigt es
   kein zweites Mal

Für das Firmenpostfach: hängt vom Anbieter ab. Bei Microsoft 365 mit aktivierter
Zwei-Faktor-Anmeldung ebenfalls ein App-Passwort, sonst das normale Postfachpasswort.

## 4. Passwörter in den Schlüsselbund

Passwörter gehören nicht in eine Datei. In den Schlüsselbund damit:

```bash
security add-generic-password -s mailtriage-icloud \
  -a julius.steinmetz -w 'xxxx-xxxx-xxxx-xxxx'

security add-generic-password -s mailtriage-firma \
  -a j.steinmetz@deine-firma.de -w '<passwort>'
```

`-a` muss exakt dem `benutzer` in `config/konten.json` entsprechen.

Prüfen:

```bash
security find-generic-password -s mailtriage-icloud -a julius.steinmetz -w
```

## 5. Serverdaten eintragen

`config/konten.json` öffnen und anpassen.

**iCloud** ist schon fertig eingetragen:

| Feld | Wert |
|---|---|
| Server | `imap.mail.me.com` |
| Port | `993` (SSL/TLS) |
| Benutzer | der Teil vor dem `@`, also `julius.steinmetz` |

Falls der Login damit scheitert: die volle Adresse als `benutzer` eintragen.

**Das Firmenpostfach** musst du nachtragen. Den Server findest du in Apple Mail unter
*Einstellungen → Accounts → \<dein Account\> → Servereinstellungen*. Häufige Fälle:

| Anbieter | IMAP-Server |
|---|---|
| Microsoft 365 / Exchange Online | `outlook.office365.com` |
| IONOS | `imap.ionos.de` |
| All-Inkl | `<deine-domain>.de` |
| Strato | `imap.strato.de` |
| Google Workspace | `imap.gmail.com` |

Trage außerdem unter `meine_adressen` alle Adressen ein, unter denen dich Post
erreicht – auch die Aliasse. Daran erkennt das Regelwerk, ob eine Mail direkt an dich
ging oder du nur in Kopie stehst.

## 6. Verbindung testen und Ordner anlegen

```bash
python3 -m mailtriage einrichten
```

Das prüft Login, Regelwerk und Ordner, ohne etwas zu verändern. Der Befehl erkennt
dabei automatisch, wie Archiv, Papierkorb und Junk auf deinem Server tatsächlich
heißen – die Namen unterscheiden sich je nach Anbieter.

Wenn Ordner fehlen:

```bash
python3 -m mailtriage einrichten --anlegen
```

Legt `Triage/1 Handeln`, `Triage/2 Wartet` und `Triage/3 Lesen` in beiden Postfächern
an. Sie erscheinen nach der nächsten Synchronisation in Apple Mail.

## 7. Erster Lauf – vorsichtig

Ein einzelnes Konto, nur lesen:

```bash
python3 -m mailtriage morgens --konto icloud
```

Dann den Bericht in `runs/` lesen. Sieht der Vorschlag plausibel aus?

**Für die ersten Wochen empfehlenswert** – nichts wird gelöscht, alles Destruktive
landet nur in der Prüfliste, damit du siehst, *was* das Regelwerk löschen würde:

```bash
python3 -m mailtriage morgens --ohne-loeschen
```

Wer noch vorsichtiger sein will, stellt das Firmenkonto in `config/konten.json`
zunächst auf `"nur_lesen": true` – dann wird es gescannt und berichtet, aber nie
verändert.

Trockenlauf – zeigt, was passieren würde, ohne es zu tun:

```bash
python3 -m mailtriage anwenden
```

Und erst wenn das stimmt:

```bash
python3 -m mailtriage anwenden --ja
```

**Vor dem ersten großen Backlog-Lauf:** Apple Mail schließen. Dann synchronisiert es
danach in einem Zug, statt tausende Einzeländerungen live mitzumachen.

## 8. Regelwerk auf dich zuschneiden

Nach ein paar Läufen siehst du im Bericht unter *Größte Absender*, wer dein Postfach
tatsächlich füllt. Für die Spitzenreiter je eine Regel ergänzen – das ist der Hebel.

In `config/regeln.json`, möglichst weit oben:

```json
{
  "name": "Immobilienverwaltung Musterhausen",
  "wenn": { "von_domain": ["hausverwaltung-musterhausen.de"] },
  "dann": { "kategorie": "immobilien", "aktion": "archivieren",
            "unterordner": "Immobilien" }
}
```

Und in `schutz` gehören die Absender, bei denen niemals etwas schiefgehen darf:

```json
"schutz": {
  "kommentar": "Nie löschen, nie als Spam",
  "von_domain": ["elster.de", "finanzamt.de", "meine-kanzlei.de", "meine-bank.de"],
  "von_adresse": ["steuerberater@kanzlei.de"]
}
```

Nach jeder Änderung prüfen:

```bash
python3 -m mailtriage einrichten --konto icloud
```

## 9. Zeitplan aktivieren

```bash
./launchd/installieren.sh
```

Richtet zwei LaunchAgents ein: 09:45 und 15:45. Sie **scannen nur** und legen den
Bericht bereit – verschoben wird nie automatisch. Wenn der Lauf durch ist, kommt eine
Mitteilung auf den Schreibtisch.

Wieder abschalten:

```bash
./launchd/installieren.sh entfernen
```

## Wenn etwas klemmt

| Symptom | Ursache |
|---|---|
| „Benutzername oder Passwort falsch" bei iCloud | Kein app-spezifisches Passwort verwendet |
| Login scheitert trotz App-Passwort | `benutzer` auf die volle Adresse umstellen |
| „Kein Passwort für Konto" | `-a` im Schlüsselbund ≠ `benutzer` in der Konfiguration |
| Ordner wird nicht gefunden | `python3 -m mailtriage einrichten` zeigt die echten Namen |
| Läuft per launchd nicht | `runs/protokoll.log` und `runs/launchd.log` ansehen |
| Apple Mail zeigt Änderungen nicht | Mail neu starten; die Änderung liegt auf dem Server |

Versehentlich zu viel verschoben? Den ganzen Lauf zurückdrehen:

```bash
python3 -m mailtriage rueckgaengig        # zeigt, was zurückkäme
python3 -m mailtriage rueckgaengig --ja   # holt es zurück
```

Oder von Hand: Alles liegt im Papierkorb bzw. im Archiv und lässt sich in Apple Mail
markieren und zurückschieben. Der vollständige Plan jedes Laufs liegt als JSON in
`runs/` – da steht für jede Mail drin, woher sie kam und wohin sie ging.

Was das System grundsätzlich nicht kann und warum, steht in
[Sicherungen](sicherungen.md).
