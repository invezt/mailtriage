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
from datetime import datetime, timezone
from pathlib import Path

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
             max_aktionen: int | None = None, leise: bool = False) -> Ergebnis:
    plan_pfad = Path(plan_pfad)
    plan = json.loads(plan_pfad.read_text(encoding="utf-8"))
    konto: Konto = cfg.konto(plan["konto"])
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
        if not leise:
            print(f"  {konto.name}: TROCKENLAUF – es wird nichts veraendert.")
            for (quelle, ziel), eintraege in sorted(gruppen.items()):
                print(f"    {quelle} → {ziel}: {len(eintraege)}")
            if ergebnis.offen:
                print(f"    (+{ergebnis.offen} ueber dem Limit von {grenze})")
            print("    Zum Ausfuehren: dieselbe Zeile noch einmal mit --ja")
        return ergebnis

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
