"""Harte Sicherungen - unabhaengig vom Regelwerk.

Der Unterschied zu den Regeln in config/regeln.json ist wichtig: Regeln kann
man aendern, und ein Tippfehler darin kann Schaden anrichten. Was hier steht,
greift *nach* dem Regelwerk und laesst sich durch keine Regel aushebeln.

Die Zusagen:

  1. Es wird nie eine Mail versendet. Dieses Werkzeug hat keine
     Versandfunktion - kein SMTP, kein Weiterleiten, kein Antworten.
  2. Es wird nie endgueltig geloescht. "Loeschen" heisst ausschliesslich
     Verschieben in den Papierkorb. Der Papierkorb wird nie geleert.
  3. Frische Mail wird nie automatisch geloescht, egal welche Regel greift.
  4. Postausgang, Entwuerfe, Papierkorb und Spam werden nie als Quelle
     gelesen und damit nie umsortiert.
  5. Nachrichteninhalte werden nie geladen - nur Kopfzeilen.
  6. Eine einzelne Regel, die fast alles wegraeumen will, loest die
     Notbremse aus. Das faengt den kaputten Regeleintrag ab.

Punkt 1, 2 und 5 sind in tests/test_guards.py als Test hinterlegt, der den
Quelltext selbst prueft. Sie bleiben damit auch dann wahr, wenn spaeter
jemand - ich eingeschlossen - etwas dazubaut.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .model import Message
from .rules import Entscheidung
from .taxonomy import DESTRUKTIVE_AKTIONEN

# Frischer als das wird nichts automatisch geloescht - egal was die Regel sagt.
MINDESTALTER_LOESCHEN_TAGE = 30

# Notbremse: wenn fast alles weggeraeumt werden soll und *eine* Regel dafuer
# verantwortlich ist, stimmt mit hoher Wahrscheinlichkeit die Regel nicht.
NOTBREMSE_AB_ANZAHL = 100
NOTBREMSE_ANTEIL_DESTRUKTIV = 0.90
NOTBREMSE_ANTEIL_EINE_REGEL = 0.80

# Ordner, die nie gelesen und nie umsortiert werden.
GESPERRTE_QUELLEN = re.compile(
    r"^(inbox[./])?\s*("
    # Postausgang
    r"sent(\s*(messages|items|mail|e-?mails?))?|"
    r"gesendete?(\s*(objekte|elemente|e-?mails?|nachrichten))?|"
    # Entwuerfe
    r"drafts?|entw(ue|u|\u00fc)rfe?|"
    # Papierkorb
    r"trash|papierkorb|bin|"
    r"deleted(\s*(messages|items|e-?mails?))?|"
    r"gel(oe|\u00f6)schte?(\s*(objekte|elemente|e-?mails?|nachrichten))?|"
    # Spam
    r"junk([\s-]*e?[\s-]*mails?)?|spam(verdacht)?|bulk\s*mail|werbung|"
    # Apple/Exchange-Sonderformen
    r"notes|notizen|archive\s*\(gel(oe|\u00f6)scht\)"
    r")\s*$",
    re.IGNORECASE,
)


class GuardError(RuntimeError):
    """Eine harte Sicherung hat angeschlagen. Nicht umgehbar."""


def ist_gesperrte_quelle(ordner: str) -> bool:
    return bool(GESPERRTE_QUELLEN.match(ordner.strip()))


def pruefe_quellordner(ordner: str) -> None:
    """Postausgang, Entwuerfe, Papierkorb und Spam werden nie angefasst."""
    if ist_gesperrte_quelle(ordner):
        raise GuardError(
            f"Ordner {ordner!r} wird nicht als Quelle gelesen. "
            "Postausgang, Entwuerfe, Papierkorb und Spam bleiben unberuehrt - "
            "das ist fest verdrahtet und laesst sich nicht per Konfiguration aendern."
        )


def erzwinge_mindestalter(entscheidung: Entscheidung, msg: Message,
                          jetzt: datetime | None = None,
                          tage: int = MINDESTALTER_LOESCHEN_TAGE) -> Entscheidung:
    """Frische Mail wird nie automatisch weggeraeumt.

    Greift *nach* dem Regelwerk. Selbst eine Regel, die alles loeschen will,
    kommt an dieser Grenze nicht vorbei.
    """
    if entscheidung.aktion not in DESTRUKTIVE_AKTIONEN:
        return entscheidung

    jetzt = jetzt or datetime.now(timezone.utc)
    alter = msg.age_days(jetzt)
    if alter >= tage:
        return entscheidung

    # Offensichtlicher Massenversand darf auch frisch in den Spam-Ordner -
    # sonst waere die Spam-Erkennung wirkungslos. Echte Post an dich nie.
    if entscheidung.aktion == "spam" and (msg.is_bulk or msg.spam_flagged):
        return entscheidung

    entscheidung.aktion = "pruefen"
    entscheidung.zielordner = None
    entscheidung.schutz = f"juenger als {tage} Tage"
    return entscheidung


def ohne_loeschen(entscheidung: Entscheidung) -> Entscheidung:
    """Eingewoehnungsmodus: nichts Destruktives, alles zur Vorlage."""
    if entscheidung.aktion in DESTRUKTIVE_AKTIONEN:
        entscheidung.aktion = "pruefen"
        entscheidung.zielordner = None
        entscheidung.schutz = "Eingewoehnungsmodus (--ohne-loeschen)"
    return entscheidung


def notbremse(eintraege: list[dict]) -> str:
    """Prueft, ob ein Lauf nach einem kaputten Regeleintrag aussieht.

    Gibt den Grund zurueck, wenn angehalten werden soll - sonst "".
    """
    gesamt = len(eintraege)
    if gesamt < NOTBREMSE_AB_ANZAHL:
        return ""

    destruktiv = [e for e in eintraege if e.get("aktion") in DESTRUKTIVE_AKTIONEN]
    if not destruktiv:
        return ""

    anteil = len(destruktiv) / gesamt
    if anteil <= NOTBREMSE_ANTEIL_DESTRUKTIV:
        return ""

    # Viele verschiedene Regeln, die aufraeumen, sind normal - etwa eine alte
    # Woche voller Newsletter. Verdaechtig ist, wenn *eine* Regel fast alles
    # abraeumt. Das ist das Muster eines zu weit gefassten Eintrags.
    je_regel: dict[str, int] = {}
    for e in destruktiv:
        name = e.get("regel", "(unbenannt)")
        je_regel[name] = je_regel.get(name, 0) + 1
    name, anzahl = max(je_regel.items(), key=lambda kv: kv[1])
    if anzahl / len(destruktiv) <= NOTBREMSE_ANTEIL_EINE_REGEL:
        return ""

    return (
        f"Notbremse: {len(destruktiv)} von {gesamt} Nachrichten "
        f"({anteil:.0%}) sollen weggeraeumt werden, davon {anzahl} "
        f"({anzahl / len(destruktiv):.0%}) durch die einzelne Regel {name!r}.\n"
        f"    Das sieht nach einer zu weit gefassten Regel aus. Pruefe sie in "
        f"config/regeln.json.\n"
        f"    Ist der Vorschlag richtig so, denselben Befehl mit --notbremse-loesen "
        f"wiederholen."
    )


def pruefe_schreibrecht(konto) -> None:
    """Konten mit nur_lesen werden nie veraendert."""
    if getattr(konto, "nur_lesen", False):
        raise GuardError(
            f"Konto {konto.name!r} steht auf nur_lesen. Es wird gescannt und "
            "berichtet, aber nichts verschoben. Zum Aendern nur_lesen in "
            "config/konten.json auf false setzen."
        )
