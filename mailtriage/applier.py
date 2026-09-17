"""Anwenden: den Plan ausfuehren.

Sicherheitsnetze, die hier eingebaut sind:

  * Ohne --ja passiert nichts (Trockenlauf ist der Normalfall).
  * max_aktionen_pro_lauf begrenzt, wie viel eine einzelne Ausfuehrung
    bewegt. Lieber zweimal laufen lassen als Apple Mail ueberfahren.
  * Erledigte Eintraege werden im Plan abgehakt. Ein zweiter Aufruf macht
    da weiter, wo der erste aufgehoert hat - nichts wird doppelt bewegt.
  * "loeschen" heisst Papierkorb. Der Papierkorb wird nie geleert.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import guards
from .config import Config, Konto
from .mailbox import Mailbox, MailboxError
from .taxonomy import PASSIVE_AKTIONEN


@dataclass
class Ergebnis:
    konto: str
    bewegt: int = 0
    uebersprungen: int = 0
    offen: int = 0
    fehler: list[str] = field(default_factory=list)
    je_ziel: dict[str, int] = field(default_factory=dict)
    nicht_gefunden: int = 0

    def zusammenfassung(self) -> str:
        teile = [f"{self.bewegt} bewegt"]
        if self.offen:
            teile.append(f"{self.offen} offen (Limit erreicht)")
        if self.fehler:
            teile.append(f"{len(self.fehler)} Fehler")
        return f"{self.konto}: " + ", ".join(teile)


def _benoetigte_ordner(eintraege: list[dict]) -> set[str]:
    return {e["ziel"] for e in eintraege if e.get("ziel")}


def wende_an(plan_pfad: Path, cfg: Config, *, ja: bool = False,
             max_aktionen: int | None = None, leise: bool = False,
             notbremse_loesen: bool = False) -> Ergebnis:
    plan_pfad = Path(plan_pfad)
    plan = json.loads(plan_pfad.read_text(encoding="utf-8"))
    konto: Konto = cfg.konto(plan["konto"])

    # Notbremse: sieht der Plan nach einer zu weit gefassten Regel aus?
    if not notbremse_loesen:
        grund = guards.notbremse(plan["eintraege"])
        if grund:
            raise guards.GuardError(grund)
    grenze = max_aktionen or cfg.einstellungen.max_aktionen_pro_lauf
    ergebnis = Ergebnis(konto=konto.name)

    offen = [e for e in plan["eintraege"]
             if e.get("ziel") and e["aktion"] not in PASSIVE_AKTIONEN
             and not e.get("erledigt")]
    ergebnis.uebersprungen = len(plan["eintraege"]) - len(offen)

    if not offen:
        if not leise:
            print(f"  {konto.name}: nichts zu tun.")
        return ergebnis

    # Gruppieren: ein MOVE-Kommando pro (Quelle -> Ziel).
    gruppen: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    budget = grenze
    for e in offen:
        if budget <= 0:
            ergebnis.offen += 1
            continue
        gruppen[(e["ordner"], e["ziel"])].append(e)
        budget -= 1

    if not ja:
        if not leise and konto.nur_lesen:
            print(f"  {konto.name}: steht auf nur_lesen - hier wird nie etwas bewegt.")
        if not leise:
            print(f"  {konto.name}: TROCKENLAUF – es wird nichts veraendert.")
            for (quelle, ziel), eintraege in sorted(gruppen.items()):
                print(f"    {quelle} → {ziel}: {len(eintraege)}")
            if ergebnis.offen:
                print(f"    (+{ergebnis.offen} ueber dem Limit von {grenze})")
            print("    Zum Ausfuehren: dieselbe Zeile noch einmal mit --ja")
        return ergebnis

    # Konten mit nur_lesen werden gescannt und berichtet, aber nie veraendert.
    guards.pruefe_schreibrecht(konto)

    passwort = konto.passwort()
    with Mailbox(konto.name, konto.host, konto.port, konto.benutzer,
                 passwort, verbose=not leise) as box:
        vorhanden = set(box.folders()["alle"])
        for ziel in sorted(_benoetigte_ordner(offen)):
            if ziel not in vorhanden:
                try:
                    box.ensure_folder(ziel)
                except MailboxError as exc:
                    ergebnis.fehler.append(str(exc))

        for (quelle, ziel), eintraege in sorted(gruppen.items()):
            uids = [e["uid"] for e in eintraege]
            try:
                anzahl = box.move(quelle, uids, ziel)
            except MailboxError as exc:
                ergebnis.fehler.append(f"{quelle} → {ziel}: {exc}")
                continue
            ergebnis.bewegt += anzahl
            ergebnis.je_ziel[ziel] = ergebnis.je_ziel.get(ziel, 0) + anzahl
            for e in eintraege:
                e["erledigt"] = True

    plan["angewendet"] = datetime.now(timezone.utc).isoformat(timespec="seconds") \
        if ergebnis.offen == 0 and not ergebnis.fehler else None
    plan["zuletzt_ausgefuehrt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    plan["bewegt_gesamt"] = sum(1 for e in plan["eintraege"] if e.get("erledigt"))
    plan_pfad.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    return ergebnis


def mache_rueckgaengig(plan_pfad: Path, cfg: Config, *, ja: bool = False,
                       leise: bool = False) -> Ergebnis:
    """Einen ausgefuehrten Plan zurueckdrehen.

    Nach einem MOVE hat die Nachricht im Zielordner eine neue UID - die alte
    zeigt ins Leere. Wiedergefunden wird sie deshalb ueber die Message-ID,
    die jede Mail dauerhaft mit sich traegt.

    Das Zeitfenster fuer die Suche kommt aus den Nachrichtendaten selbst, nicht
    aus dem Ausfuehrungszeitpunkt: IMAP behaelt das INTERNALDATE beim
    Verschieben bei, eine Mail von 2019 liegt also auch im Papierkorb mit
    Datum 2019.
    """
    plan_pfad = Path(plan_pfad)
    plan = json.loads(plan_pfad.read_text(encoding="utf-8"))
    konto: Konto = cfg.konto(plan["konto"])
    ergebnis = Ergebnis(konto=konto.name)

    erledigt = [e for e in plan["eintraege"]
                if e.get("erledigt") and e.get("ziel")]
    if not erledigt:
        if not leise:
            print(f"  {konto.name}: in diesem Plan wurde nichts ausgefuehrt.")
        return ergebnis

    ohne_id = [e for e in erledigt if not e.get("message_id")]
    ergebnis.nicht_gefunden = len(ohne_id)
    brauchbar = [e for e in erledigt if e.get("message_id")]

    nach_ziel: defaultdict[str, list[dict]] = defaultdict(list)
    for e in brauchbar:
        nach_ziel[e["ziel"]].append(e)

    if not ja:
        if not leise:
            print(f"  {konto.name}: TROCKENLAUF \u2013 es wird nichts zurueckgeholt.")
            for ziel, eintraege in sorted(nach_ziel.items()):
                quellen = {e["ordner"] for e in eintraege}
                print(f"    {ziel} \u2192 {', '.join(sorted(quellen))}: {len(eintraege)}")
            if ohne_id:
                print(f"    {len(ohne_id)} ohne Message-ID \u2013 nicht auffindbar, "
                      "die musst du in Apple Mail von Hand zurueckschieben.")
            print("    Zum Ausfuehren: dieselbe Zeile noch einmal mit --ja")
        return ergebnis

    guards.pruefe_schreibrecht(konto)
    passwort = konto.passwort()

    with Mailbox(konto.name, konto.host, konto.port, konto.benutzer,
                 passwort, verbose=not leise) as box:
        for ziel, eintraege in sorted(nach_ziel.items()):
            daten = sorted(datetime.fromisoformat(e["datum"]) for e in eintraege)
            since = daten[0] - timedelta(days=1)
            before = daten[-1] + timedelta(days=2)

            try:
                uids = box.search_window(ziel, since=since, before=before)
                vorhandene = box.fetch_headers(ziel, uids)
            except MailboxError as exc:
                ergebnis.fehler.append(f"{ziel}: {exc}")
                continue

            nach_id = {m.message_id: m.uid for m in vorhandene if m.message_id}

            zurueck: defaultdict[str, list[tuple[int, dict]]] = defaultdict(list)
            for e in eintraege:
                uid = nach_id.get(e["message_id"])
                if uid is None:
                    ergebnis.nicht_gefunden += 1
                    continue
                zurueck[e["ordner"]].append((uid, e))

            for quelle, paare in sorted(zurueck.items()):
                try:
                    anzahl = box.move(ziel, [u for u, _ in paare], quelle)
                except MailboxError as exc:
                    ergebnis.fehler.append(f"{ziel} \u2192 {quelle}: {exc}")
                    continue
                ergebnis.bewegt += anzahl
                ergebnis.je_ziel[quelle] = ergebnis.je_ziel.get(quelle, 0) + anzahl
                for _, e in paare:
                    e["erledigt"] = False
                    e["rueckgaengig"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds")

    plan["angewendet"] = None
    plan["bewegt_gesamt"] = sum(1 for e in plan["eintraege"] if e.get("erledigt"))
    plan_pfad.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    return ergebnis
