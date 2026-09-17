# Der Tagesrhythmus: 10:00 und 16:00

## Kurz vorweg: was ich von deinen Zeiten halte

**Zweimal am Tag ist richtig.** Wer Mail funktionierend im Griff behält, macht das in
zwei bis drei festen Blöcken – nicht nebenbei über den Tag verteilt. Zwei Blöcke sind
die schlanke Variante davon.

**10:00 ist gut gewählt, gerade weil es nicht 8:00 ist.** Die erste Stunde im Büro ist
die einzige, die verlässlich ungestört ist. Die an Mail zu verlieren, ist teuer. Um
10:00 ist der Tag angelaufen, und was über Nacht hereinkam, wird früh genug gesehen,
um noch am selben Tag etwas damit anzufangen.

**16:00 ist die bessere Entscheidung als abends – aus drei Gründen:**

1. **Du kannst noch handeln.** Was du um 16:00 findest, lässt sich heute noch
   beantworten, weiterleiten oder anrufen. Was du um 20:00 findest, kannst du nur noch
   mit dir herumtragen. Das ist die schlechteste aller Varianten: Du hast die
   Belastung, aber nicht die Handlungsmöglichkeit.
2. **Es schließt den Tag wirklich ab.** Du hast gesagt, dass dir das wichtig ist. Genau
   das leistet ein Block am späten Nachmittag – und eine Abendrunde leistet es nicht,
   weil sie den Kopf noch einmal aufmacht, statt ihn zuzumachen.
3. **Der Abend bleibt frei.** Ein fester Schnitt um 16:00 macht das „ich schau nur kurz
   nochmal rein" überflüssig, weil es eine verlässliche nächste Gelegenheit gibt.

Das einzige Risiko bei 16:00: Es ist die Zeit, zu der Termine überziehen. Deshalb
startet der Scan automatisch schon um **15:45**, damit der Bericht fertig ist, wenn du
dich hinsetzt. Und deshalb ist der Block zweigeteilt – wenn du nur fünf Minuten hast,
machst du den ersten Teil und lässt den zweiten liegen.

## Was in welcher Session passiert

### 10:00 – die Runde (10 Minuten)

Nur, was seit dem letzten Lauf neu dazugekommen ist. **Kein Backlog.** Backlog am
Morgen würde genau die Zeit auffressen, die du für echte Arbeit brauchst.

```
python3 -m mailtriage morgens          # läuft automatisch um 09:45
# Bericht lesen: runs/<datum>-*-taeglich.md
python3 -m mailtriage anwenden --ja
```

Danach liegt im Posteingang nur noch, was in `pruefen` gelandet ist – die Mails, die
keine Regel sicher einordnen konnte. Die gehst du von Hand durch. Das sind
erfahrungsgemäß wenige Prozent.

### 16:00 – der Abschluss (20–25 Minuten)

**Teil 1 (10 Min): die Tagespost.** Wie morgens. Danach ist der Tag sauber.

**Teil 2 (10–15 Min): eine Woche Backlog.** Das System nimmt die nächste unbearbeitete
Woche und arbeitet sich rückwärts durch die Zeit.

```
python3 -m mailtriage nachmittags      # läuft automatisch um 15:45
python3 -m mailtriage anwenden --ja
```

Wenn der Nachmittag eng wird: Teil 2 weglassen. Der Cursor bleibt stehen, morgen geht
es an derselben Stelle weiter. Nichts geht verloren, nichts staut sich auf.

## Warum rückwärts und nicht vorwärts

Von neu nach alt, nicht von alt nach neu. Zwei Gründe:

- Was vor drei Wochen liegen blieb, ist eher noch relevant als das aus 2019. Du willst
  das Wertvolle zuerst finden, nicht zuletzt.
- Je weiter du zurückgehst, desto eindeutiger wird die Sache. Alte Mail ist fast immer
  archivieren oder löschen. Die Läufe werden also schneller, je länger du dabei bist –
  nicht langsamer.

Das Regelwerk ist darauf abgestimmt: Bei alter Mail greifen andere Regeln als bei
frischer. Eine Mail von heute, die direkt an dich ging, landet in *Handeln*. Dieselbe
Mail, 30 Tage alt, landet im *Archiv* – denn nach einem Monat ist sie Geschichte, kein
Arbeitsvorrat. Was wirklich offen war, kommt ohnehin als Nachfrage zurück.

## Wie lange dauert der Backlog

Die wichtige Nachricht zuerst: **Der Backlog wächst nicht mehr.** Sobald die täglichen
Läufe stehen, bleibt der Rückstand fest – jede abgearbeitete Woche ist echter
Fortschritt.

Bei drei Jahren Rückstand (rund 156 Wochen), 5 Sessions pro Woche:

| Vorgehen | Rechnung | Dauer |
|---|---|---|
| Eine Woche pro Session | 156 ÷ 5 | **gut 7 Monate** |
| Vier Wochen pro Session (`--wochen 4`) | 156 ÷ 20 | **rund 8 Wochen** |
| Altlast-Schnitt + vier Wochen pro Session | 52 ÷ 20 | **rund 3 Wochen** |

Eine Woche pro Tag ist zu langsam, wenn der Rückstand Jahre alt ist. Zwei Hebel:

**`--wochen 4`** – der Nachmittagsblock nimmt vier Wochen statt einer. Der Bericht
bleibt gleich kurz, weil er aggregiert. Der Aufwand für dich ändert sich kaum, weil
du ohnehin nur Summen prüfst und die *pruefen*-Liste durchgehst.

```
python3 -m mailtriage nachmittags --wochen 4
```

**Der Altlast-Schnitt** – alles, was älter als zwölf Monate ist, in einem Rutsch. Das
ist keine Kapitulation, sondern die bewusste Entscheidung, die dieses Vorgehen
überhaupt erst tragfähig macht: Mail, die ein Jahr ungelesen lag, wird nicht mehr
bearbeitet. Sie wird archiviert und bleibt durchsuchbar.

```
python3 -m mailtriage backlog --wochen 52    # ein Jahr am Stück
python3 -m mailtriage anwenden --ja
```

Die Schutzregeln greifen auch hier: Markiertes und Geschütztes wird nicht angefasst,
sondern vorgelegt. Und gelöscht heißt Papierkorb, nicht weg.

Mein Vorschlag für den Start: **einmal den Altlast-Schnitt** für alles vor
September 2025, danach **`--wochen 4`** im Nachmittagsblock. Dann ist der Rückstand in
etwa einem Monat erledigt statt in einem Dreivierteljahr.

## Kalendereinträge

Zwei wiederkehrende Termine, damit der Rhythmus trägt:

| Zeit | Dauer | Titel |
|---|---|---|
| 10:00 | 15 Min | Mail-Triage – Runde |
| 16:00 | 25 Min | Mail-Triage – Tagesabschluss |

Den 16:00-Termin als letzten Termin des Tages setzen, nicht zwischen zwei andere. Er
soll der Schlussstrich sein.
