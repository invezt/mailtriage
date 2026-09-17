"""Fortschritt beim Zurückarbeiten.

Der Backlog wird wochenweise von neu nach alt abgearbeitet: die juengsten
Altmails zuerst. Das ist bewusst so herum - was gerade erst liegen blieb,
ist am ehesten noch relevant, und was aus 2019 stammt, laesst sich am Ende
meist in einem Rutsch archivieren.

Pro Konto wird ein Cursor gefuehrt: das Datum, bis zu dem zurueckgearbeitet
wurde. Jeder Backlog-Lauf nimmt die Woche davor und schiebt den Cursor
weiter. Damit kann man jederzeit aufhoeren und am naechsten Tag weitermachen.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import STATE_DIR

STATUS_DATEI = STATE_DIR / "fortschritt.json"


def _heute() -> date:
    return datetime.now(timezone.utc).date()


def _als_datum(wert) -> date | None:
    if not wert:
        return None
    if isinstance(wert, date):
        return wert
    return date.fromisoformat(str(wert)[:10])


@dataclass
class KontoStatus:
    backlog_cursor: str = ""        # bis hierher zurueckgearbeitet (exklusiv)
    aeltester_fund: str = ""        # aelteste je gesehene Nachricht
    wochen_erledigt: int = 0
    mails_bearbeitet: int = 0
    letzter_taeglicher_lauf: str = ""
    letzter_backlog_lauf: str = ""
    backlog_fertig: bool = False
    leere_fenster_in_folge: int = 0

    def cursor(self, taegliches_fenster_tage: int = 7) -> date:
        vorhanden = _als_datum(self.backlog_cursor)
        return vorhanden or (_heute() - timedelta(days=taegliches_fenster_tage))


@dataclass
class Fortschritt:
    konten: dict[str, KontoStatus] = field(default_factory=dict)

    def fuer(self, konto: str) -> KontoStatus:
        return self.konten.setdefault(konto, KontoStatus())


def lade(pfad: Path | None = None) -> Fortschritt:
    pfad = pfad or STATUS_DATEI
    if not pfad.exists():
        return Fortschritt()
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return Fortschritt()
    bekannt = set(KontoStatus.__dataclass_fields__)
    return Fortschritt(konten={
        name: KontoStatus(**{k: v for k, v in werte.items() if k in bekannt})
        for name, werte in roh.get("konten", {}).items()
    })


def speichere(fortschritt: Fortschritt, pfad: Path | None = None) -> None:
    pfad = pfad or STATUS_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(
        {"aktualisiert": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "konten": {n: asdict(s) for n, s in sorted(fortschritt.konten.items())}},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def backlog_fenster(status: KontoStatus, fenster_tage: int = 7,
                    taegliches_fenster_tage: int = 7) -> tuple[date, date]:
    """Die naechste abzuarbeitende Woche als [von, bis)."""
    bis = status.cursor(taegliches_fenster_tage)
    return bis - timedelta(days=fenster_tage), bis


def nach_backlog_lauf(status: KontoStatus, von: date, anzahl: int,
                      aeltester: date | None = None) -> KontoStatus:
    """Cursor weiterschieben, nachdem eine Woche erledigt ist."""
    status.backlog_cursor = von.isoformat()
    status.wochen_erledigt += 1
    status.mails_bearbeitet += anzahl
    status.letzter_backlog_lauf = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if aeltester:
        bisher = _als_datum(status.aeltester_fund)
        if bisher is None or aeltester < bisher:
            status.aeltester_fund = aeltester.isoformat()

    # Mehrere leere Wochen hintereinander: der Backlog ist durch. Das faengt
    # den Fall ab, dass zwischendrin einfach mal ein paar Wochen Ruhe war.
    status.leere_fenster_in_folge = 0 if anzahl else status.leere_fenster_in_folge + 1
    aeltester_bekannt = _als_datum(status.aeltester_fund)
    if status.leere_fenster_in_folge >= 8 or (
            aeltester_bekannt and von <= aeltester_bekannt):
        status.backlog_fertig = True
    return status


def taegliches_fenster(status: KontoStatus, fenster_tage: int = 7) -> date:
    """Ab wann beim taeglichen Lauf gesucht wird (SINCE-Grenze)."""
    letzter = _als_datum(status.letzter_taeglicher_lauf)
    if letzter is None:
        return _heute() - timedelta(days=fenster_tage)
    # Einen Tag Ueberlappung: IMAP sucht auf Tagesgenauigkeit, so geht
    # bei einem Lauf um 10:00 und einem um 16:00 nichts verloren.
    return letzter - timedelta(days=1)


def nach_taeglichem_lauf(status: KontoStatus, anzahl: int) -> KontoStatus:
    status.letzter_taeglicher_lauf = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status.mails_bearbeitet += anzahl
    return status
