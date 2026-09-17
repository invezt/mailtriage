"""Regelwerk: aus einer Nachricht wird eine Entscheidung.

Die Regeln werden von oben nach unten geprueft, die erste passende gewinnt.
Passt keine, greift der Standard - und der ist bewusst "pruefen": im Zweifel
wird nichts angefasst. Ein Backlog aufzuraeumen darf nie bedeuten, dass auf
Verdacht geloescht wird.

Zwei Sicherheitsnetze liegen ueber allen Regeln:

  1. Eine markierte Nachricht (Fahne in Apple Mail) wird nie geloescht.
  2. Absender aus der Schutzliste werden nie geloescht.

In beiden Faellen wird die Aktion auf "pruefen" heruntergestuft, statt die
Regel einfach zu ignorieren - so taucht der Fall im Bericht auf.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Konto
from .model import Message
from .taxonomy import (
    AKTIONEN,
    DESTRUKTIVE_AKTIONEN,
    pruefe_aktion,
    pruefe_kategorie,
)


@dataclass
class Entscheidung:
    kategorie: str
    aktion: str
    regel: str
    zielordner: str | None
    begruendung: str = ""
    schutz: str = ""

    @property
    def bewegt(self) -> bool:
        return self.zielordner is not None


def _als_liste(wert) -> list[str]:
    if wert is None:
        return []
    if isinstance(wert, str):
        return [wert]
    return [str(w) for w in wert]


def _domain_passt(domain: str, muster: str) -> bool:
    """'example.com' passt auf 'example.com' und 'mail.example.com'."""
    domain, muster = domain.lower(), muster.lower().lstrip("@.")
    return domain == muster or domain.endswith("." + muster)


def passt(bedingung: dict, msg: Message, konto: Konto,
          jetzt: datetime | None = None) -> bool:
    """Alle angegebenen Bedingungen muessen zutreffen (UND-Verknuepfung)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    betreff = msg.subject.lower()
    absender = f"{msg.from_name} {msg.from_addr}".lower()

    for schluessel, wert in bedingung.items():
        if schluessel in ("kommentar", "beispiel"):
            continue

        if schluessel == "von_domain":
            if not any(_domain_passt(msg.from_domain, m) for m in _als_liste(wert)):
                return False
        elif schluessel == "von_adresse":
            if msg.from_addr not in {a.lower() for a in _als_liste(wert)}:
                return False
        elif schluessel == "von_enthaelt":
            if not any(m.lower() in absender for m in _als_liste(wert)):
                return False
        elif schluessel == "an_adresse":
            ziele = {a.lower() for a in _als_liste(wert)}
            if not ziele.intersection(msg.to_addrs):
                return False
        elif schluessel == "betreff_enthaelt":
            if not any(m.lower() in betreff for m in _als_liste(wert)):
                return False
        elif schluessel == "betreff_regex":
            if not re.search(str(wert), msg.subject, re.IGNORECASE):
                return False
        elif schluessel == "ordner":
            if msg.folder not in _als_liste(wert):
                return False
        elif schluessel == "hat_unsubscribe":
            if bool(wert) != msg.has_unsubscribe:
                return False
        elif schluessel == "hat_list_id":
            if bool(wert) != bool(msg.list_id):
                return False
        elif schluessel == "ist_massenversand":
            if bool(wert) != msg.is_bulk:
                return False
        elif schluessel == "ungelesen":
            if bool(wert) != (not msg.seen):
                return False
        elif schluessel == "beantwortet":
            if bool(wert) != msg.answered:
                return False
        elif schluessel == "markiert":
            if bool(wert) != msg.flagged:
                return False
        elif schluessel == "spam_verdacht":
            if bool(wert) != msg.spam_flagged:
                return False
        elif schluessel == "an_mich_direkt":
            direkt = bool(set(konto.meine_adressen).intersection(msg.to_addrs))
            if bool(wert) != direkt:
                return False
        elif schluessel == "aelter_als_tage":
            if msg.age_days(jetzt) <= float(wert):
                return False
        elif schluessel == "neuer_als_tage":
            if msg.age_days(jetzt) >= float(wert):
                return False
        elif schluessel == "groesser_als_mb":
            if msg.size < float(wert) * 1024 * 1024:
                return False
        else:
            raise ValueError(
                f"Unbekannte Bedingung {schluessel!r} im Regelwerk. "
                f"Erlaubt sind u.a.: von_domain, von_adresse, betreff_enthaelt, "
                f"ist_massenversand, aelter_als_tage, ungelesen, markiert."
            )
    return True


def _greift_schutz(msg: Message, schutz: dict, konto: Konto) -> str:
    """Gibt den Grund zurueck, warum nicht geloescht werden darf - sonst ''."""
    if msg.flagged:
        return "in Apple Mail markiert"
    if not schutz:
        return ""
    if passt({k: v for k, v in schutz.items() if k != "kommentar"}, msg, konto):
        return schutz.get("kommentar") or "Schutzliste"
    return ""


def zielordner(aktion: str, konto: Konto, unterordner: str = "") -> str | None:
    _, rolle = AKTIONEN[aktion]
    if rolle is None:
        return None
    basis = konto.ordner_fuer(rolle)
    if unterordner and rolle == "archiv":
        return f"{basis}/{unterordner}"
    return basis


def klassifiziere(msg: Message, regeln: list[dict], standard: dict,
                  schutz: dict, konto: Konto,
                  jetzt: datetime | None = None) -> Entscheidung:
    """Eine Nachricht -> eine Entscheidung."""
    jetzt = jetzt or datetime.now(timezone.utc)

    treffer_name = "Standard"
    dann = dict(standard)
    for regel in regeln:
        if passt(regel.get("wenn", {}), msg, konto, jetzt):
            treffer_name = regel.get("name", "(unbenannt)")
            dann = dict(regel.get("dann", {}))
            break

    kategorie = pruefe_kategorie(dann.get("kategorie", "unklar"))
    aktion = pruefe_aktion(dann.get("aktion", "pruefen"))
    begruendung = dann.get("begruendung", "")

    schutz_grund = ""
    if aktion in DESTRUKTIVE_AKTIONEN:
        schutz_grund = _greift_schutz(msg, schutz, konto)
        if schutz_grund:
            aktion = "pruefen"

    return Entscheidung(
        kategorie=kategorie,
        aktion=aktion,
        regel=treffer_name,
        zielordner=zielordner(aktion, konto, dann.get("unterordner", "")),
        begruendung=begruendung,
        schutz=schutz_grund,
    )


def pruefe_regelwerk(regeln: list[dict], standard: dict, konto: Konto) -> list[str]:
    """Regelwerk auf Fehler pruefen, bevor es auf echte Mails losgelassen wird."""
    probleme: list[str] = []
    beispiel = Message(account=konto.name, folder="INBOX", uid=1,
                       date=datetime.now(timezone.utc), size=1)

    for index, regel in enumerate(regeln, start=1):
        name = regel.get("name") or f"Regel {index}"
        if "wenn" not in regel or not regel["wenn"]:
            probleme.append(f"{name}: kein 'wenn' - wuerde auf jede Mail passen.")
        if "dann" not in regel:
            probleme.append(f"{name}: kein 'dann' - unklar, was passieren soll.")
            continue
        try:
            pruefe_kategorie(regel["dann"].get("kategorie", "unklar"))
            pruefe_aktion(regel["dann"].get("aktion", "pruefen"))
        except ValueError as exc:
            probleme.append(f"{name}: {exc}")
        try:
            passt(regel.get("wenn", {}), beispiel, konto)
        except (ValueError, re.error) as exc:
            probleme.append(f"{name}: {exc}")

    try:
        pruefe_kategorie(standard.get("kategorie", "unklar"))
        pruefe_aktion(standard.get("aktion", "pruefen"))
    except ValueError as exc:
        probleme.append(f"Standard: {exc}")
    return probleme
