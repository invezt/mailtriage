"""Die Kategorien und Aktionen - eine Stelle, auf die sich Code und Doku beziehen.

Zwei getrennte Dimensionen, und das ist Absicht:

  KATEGORIE = worum geht es?        (geschaeftlich, immobilien, investment, ...)
  AKTION    = was passiert damit?   (handeln, archivieren, loeschen, ...)

Die Aktion bestimmt den Ordner, die Kategorie nicht. Sonst entsteht ein
Ordnerwald, in dem beim Ablegen jedes Mal nachgedacht werden muss - der
haeufigste Grund, warum solche Systeme nach ein paar Wochen einschlafen.
Die Kategorie steuert stattdessen, welche Aktion vorgeschlagen wird, und
gliedert den Bericht.
"""

from __future__ import annotations

KATEGORIEN = {
    "geschaeftlich": "Beruflich: Mandanten, Kollegen, Projekte, Termine",
    "immobilien": "Objekte, Verwaltung, Makler, Mieter, Handwerker, Energie",
    "investment": "Beteiligungen, Depots, Fonds, Reportings, Kapitalanlage",
    "finanzen": "Bank, Versicherung, Steuer, Rechnungen, Vertraege, Behoerden",
    "persoenlich": "Familie, Freunde, Privates",
    "benachrichtigung": "Automatische Mails: Bestellungen, Versand, Logins, Systemmeldungen",
    "newsletter": "Massenversand: Werbung, Verteiler, Magazine",
    "spam": "Unerwuenscht oder betruegerisch",
    "unklar": "Nicht sicher einzuordnen - Entscheidung durch dich",
}

# Aktion -> (Kurzbeschreibung, Ordnerrolle oder None wenn nichts bewegt wird)
AKTIONEN = {
    "handeln": ("Braucht eine Antwort oder eine Aufgabe von dir", "handeln"),
    "wartet": ("Du hast geliefert, wartest auf Antwort", "wartet"),
    "lesen": ("Interessant, aber nicht dringend", "lesen"),
    "archivieren": ("Aufheben zum Nachschlagen, nichts zu tun", "archiv"),
    "loeschen": ("Weg damit - landet im Papierkorb, nicht im Nirwana", "papierkorb"),
    "spam": ("Unerwuenscht - in den Spam-Ordner", "spam"),
    "behalten": ("Bleibt im Posteingang", None),
    "pruefen": ("Bleibt liegen, du entscheidest", None),
}

# Aktionen, die etwas wegnehmen. Fuer die gilt der Schutzmechanismus.
DESTRUKTIVE_AKTIONEN = frozenset({"loeschen", "spam"})

# Aktionen, bei denen nichts bewegt wird.
PASSIVE_AKTIONEN = frozenset({"behalten", "pruefen"})

# Reihenfolge fuer Berichte: oben das, was Aufmerksamkeit braucht.
AKTION_REIHENFOLGE = [
    "handeln", "pruefen", "wartet", "lesen",
    "archivieren", "loeschen", "spam", "behalten",
]

KATEGORIE_REIHENFOLGE = [
    "geschaeftlich", "immobilien", "investment", "finanzen", "persoenlich",
    "benachrichtigung", "newsletter", "spam", "unklar",
]


def pruefe_kategorie(name: str) -> str:
    if name not in KATEGORIEN:
        raise ValueError(
            f"Unbekannte Kategorie {name!r}. Erlaubt: {', '.join(sorted(KATEGORIEN))}")
    return name


def pruefe_aktion(name: str) -> str:
    if name not in AKTIONEN:
        raise ValueError(
            f"Unbekannte Aktion {name!r}. Erlaubt: {', '.join(sorted(AKTIONEN))}")
    return name
