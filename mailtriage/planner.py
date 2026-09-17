"""Planen: Postfach lesen, klassifizieren, Vorschlag schreiben.

Der Planer veraendert nichts. Er erzeugt zwei Dateien pro Lauf:

  runs/<zeit>-<konto>-<modus>.json   der vollstaendige Plan (maschinenlesbar)
  runs/<zeit>-<konto>-<modus>.md     der kompakte Bericht (fuer dich)

Erst `anwenden` fasst Nachrichten an. Diese Trennung ist der Grund, warum
man einen Backlog-Lauf beruhigt laufen lassen kann: was vorgeschlagen wird,
sieht man vorher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

from . import report, state
from .config import RUNS_DIR, Config, Konto
from .mailbox import Mailbox
from .model import Message
from .rules import Entscheidung, klassifiziere
from .taxonomy import PASSIVE_AKTIONEN


def _als_datetime(wert: date) -> datetime:
    return datetime.combine(wert, time.min, tzinfo=timezone.utc)


@dataclass
class Lauf:
    konto: str
    modus: str
    von: date | None
    bis: date | None
    eintraege: list[dict] = field(default_factory=list)
    plan_pfad: Path | None = None
    bericht_pfad: Path | None = None
    aeltester: date | None = None

    @property
    def zu_bewegen(self) -> list[dict]:
        return [e for e in self.eintraege if e["aktion"] not in PASSIVE_AKTIONEN]


def _eintrag(msg: Message, ent: Entscheidung) -> dict:
    return {
        "uid": msg.uid,
        "ordner": msg.folder,
        "ziel": ent.zielordner,
        "aktion": ent.aktion,
        "kategorie": ent.kategorie,
        "regel": ent.regel,
        "schutz": ent.schutz,
        "absender": msg.sender_label(),
        "absender_adresse": msg.from_addr,
        "betreff": msg.subject,
        "datum": msg.date.isoformat(),
        "groesse": msg.size,
        "massenversand": msg.is_bulk,
        "gelesen": msg.seen,
    }


def _fortschritt_anzeige(praefix: str):
    def zeige(fertig: int, gesamt: int) -> None:
        print(f"\r  {praefix}: {fertig}/{gesamt}", end="", flush=True)
        if fertig >= gesamt:
            print()
    return zeige


def scanne(konto: Konto, cfg: Config, modus: str, fortschritt: state.Fortschritt,
           *, jetzt: datetime | None = None, leise: bool = False,
           nur_ungelesen: bool = False) -> Lauf:
    """Liest ein Konto im gewaehlten Modus und erzeugt den Plan."""
    jetzt = jetzt or datetime.now(timezone.utc)
    status = fortschritt.fuer(konto.name)
    einst = cfg.einstellungen

    if modus == "backlog":
        von, bis = state.backlog_fenster(
            status, einst.backlog_fenster_tage, einst.taegliches_fenster_tage)
        since, before = _als_datetime(von), _als_datetime(bis)
    else:
        von = state.taegliches_fenster(status, einst.taegliches_fenster_tage)
        bis, before = None, None
        since = _als_datetime(von)

    lauf = Lauf(konto=konto.name, modus=modus, von=von, bis=bis)
    passwort = konto.passwort()

    with Mailbox(konto.name, konto.host, konto.port, konto.benutzer,
                 passwort, verbose=not leise) as box:
        for ordner in konto.quell_ordner:
            uids = box.search_window(ordner, since=since, before=before,
                                     unseen_only=nur_ungelesen)
            if not uids:
                continue
            nachrichten = box.fetch_headers(
                ordner, uids,
                progress=None if leise else _fortschritt_anzeige(f"{konto.name}/{ordner}"))
            for msg in nachrichten:
                ent = klassifiziere(msg, cfg.regeln, cfg.standard,
                                    cfg.schutz, konto, jetzt)
                lauf.eintraege.append(_eintrag(msg, ent))
                tag = msg.date.date()
                if lauf.aeltester is None or tag < lauf.aeltester:
                    lauf.aeltester = tag

    lauf.eintraege.sort(key=lambda e: e["datum"])
    return lauf


def schreibe(lauf: Lauf, cfg: Config, ordner: Path | None = None) -> Lauf:
    """Plan (JSON) und Bericht (Markdown) auf die Platte."""
    ordner = ordner or RUNS_DIR
    ordner.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y-%m-%d-%H%M")
    basis = ordner / f"{stempel}-{lauf.konto}-{lauf.modus}"

    lauf.plan_pfad = basis.with_suffix(".json")
    lauf.plan_pfad.write_text(json.dumps({
        "konto": lauf.konto,
        "modus": lauf.modus,
        "von": lauf.von.isoformat() if lauf.von else None,
        "bis": lauf.bis.isoformat() if lauf.bis else None,
        "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "angewendet": None,
        "eintraege": lauf.eintraege,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    einst = cfg.einstellungen
    fenster = None
    if lauf.von:
        fenster = (_als_datetime(lauf.von),
                   _als_datetime(lauf.bis) if lauf.bis else datetime.now(timezone.utc))

    lauf.bericht_pfad = basis.with_suffix(".md")
    lauf.bericht_pfad.write_text(report.baue_bericht(
        lauf.eintraege, konto=lauf.konto, modus=lauf.modus, fenster=fenster,
        max_zeilen=einst.bericht_max_zeilen,
        max_beispiele=einst.bericht_max_beispiele,
        top_absender=einst.bericht_top_absender,
    ), encoding="utf-8")
    return lauf


def lade_plan(pfad: Path) -> dict:
    return json.loads(Path(pfad).read_text(encoding="utf-8"))


def letzter_plan(ordner: Path | None = None, konto: str = "") -> Path | None:
    ordner = ordner or RUNS_DIR
    if not ordner.exists():
        return None
    kandidaten = [p for p in ordner.glob("*.json")
                  if not konto or f"-{konto}-" in p.name]
    # Bereits angewendete Plaene ueberspringen, damit nichts doppelt laeuft.
    offen = []
    for p in sorted(kandidaten, reverse=True):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("angewendet") is None:
                offen.append(p)
        except json.JSONDecodeError:
            continue
    return offen[0] if offen else None
