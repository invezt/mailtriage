"""Bericht - aggregiert, nie eine Zeile pro Mail.

Der Punkt dieses Moduls: der Bericht bleibt gleich gross, egal ob 50 oder
50.000 Nachrichten drinstecken. Gezeigt werden Summen, die groessten
Absender und die Faelle, die wirklich eine Entscheidung brauchen. Alles
andere wird gezaehlt, nicht aufgelistet.

Genau daran ist der letzte Anlauf gescheitert: die Menge des Outputs war
das Problem, nicht die Menge der Mails.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .taxonomy import AKTION_REIHENFOLGE, KATEGORIE_REIHENFOLGE, PASSIVE_AKTIONEN


def _tabelle(kopf: list[str], zeilen: list[list[str]]) -> list[str]:
    if not zeilen:
        return ["_(nichts)_"]
    breiten = [len(h) for h in kopf]
    for zeile in zeilen:
        for i, zelle in enumerate(zeile):
            breiten[i] = max(breiten[i], len(zelle))
    aus = ["| " + " | ".join(h.ljust(breiten[i]) for i, h in enumerate(kopf)) + " |"]
    aus.append("|" + "|".join("-" * (b + 2) for b in breiten) + "|")
    for zeile in zeilen:
        aus.append("| " + " | ".join(z.ljust(breiten[i]) for i, z in enumerate(zeile)) + " |")
    return aus


def _kuerzen(text: str, laenge: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= laenge else text[: laenge - 1] + "…"


def _anteil(teil: int, ganz: int) -> str:
    return f"{100 * teil / ganz:4.1f} %" if ganz else "   -  "


def baue_bericht(eintraege: list[dict], *, konto: str, modus: str,
                 fenster: tuple[datetime, datetime] | None,
                 max_zeilen: int = 320, max_beispiele: int = 5,
                 top_absender: int = 20, max_pruefen: int = 60) -> str:
    """eintraege: die Plan-Eintraege (dicts mit aktion/kategorie/absender/...)."""
    gesamt = len(eintraege)
    nach_aktion = Counter(e["aktion"] for e in eintraege)
    nach_kategorie = Counter(e["kategorie"] for e in eintraege)
    groesse = sum(e.get("groesse", 0) for e in eintraege)

    zeitraum = "alle"
    if fenster:
        zeitraum = f"{fenster[0]:%d.%m.%Y} bis {fenster[1]:%d.%m.%Y}"

    aus: list[str] = [
        f"# Triage-Vorschlag – {konto}",
        "",
        f"- **Modus:** {modus}",
        f"- **Zeitraum:** {zeitraum}",
        f"- **Nachrichten:** {gesamt:,}".replace(",", "."),
        f"- **Volumen:** {groesse / 1024 / 1024:,.0f} MB".replace(",", "."),
        f"- **Erstellt:** {datetime.now():%d.%m.%Y %H:%M}",
        "",
        "## Was passieren soll",
        "",
    ]

    zeilen = []
    for aktion in AKTION_REIHENFOLGE:
        anzahl = nach_aktion.get(aktion, 0)
        if anzahl:
            zeilen.append([aktion, f"{anzahl:,}".replace(",", "."), _anteil(anzahl, gesamt)])
    aus += _tabelle(["Aktion", "Anzahl", "Anteil"], zeilen)

    aus += ["", "## Worum es geht", ""]
    zeilen = []
    for kategorie in KATEGORIE_REIHENFOLGE:
        anzahl = nach_kategorie.get(kategorie, 0)
        if anzahl:
            zeilen.append([kategorie, f"{anzahl:,}".replace(",", "."), _anteil(anzahl, gesamt)])
    aus += _tabelle(["Kategorie", "Anzahl", "Anteil"], zeilen)

    # Groesste Absender - hier liegt beim Aufraeumen der meiste Hebel.
    absender: defaultdict[str, Counter] = defaultdict(Counter)
    absender_groesse: Counter = Counter()
    for e in eintraege:
        schluessel = e.get("absender_adresse") or e.get("absender") or "(unbekannt)"
        absender[schluessel][e["aktion"]] += 1
        absender_groesse[schluessel] += e.get("groesse", 0)

    rang = sorted(absender.items(), key=lambda kv: -sum(kv[1].values()))[:top_absender]
    if rang:
        aus += ["", f"## Groesste Absender (Top {len(rang)})", "",
                "_Hier lohnt sich eine Dauerregel: eine Zeile im Regelwerk "
                "erledigt diesen Absender kuenftig automatisch._", ""]
        zeilen = []
        for adresse, aktionen in rang:
            summe = sum(aktionen.values())
            haupt = aktionen.most_common(1)[0][0]
            zeilen.append([
                _kuerzen(adresse, 42),
                f"{summe:,}".replace(",", "."),
                haupt,
                f"{absender_groesse[adresse] / 1024 / 1024:.0f} MB",
            ])
        aus += _tabelle(["Absender", "Anzahl", "Meist", "Volumen"], zeilen)

    # Was du selbst entscheiden musst.
    offen = [e for e in eintraege if e["aktion"] in PASSIVE_AKTIONEN]
    geschuetzt = [e for e in offen if e.get("schutz")]
    if offen:
        aus += ["", f"## Deine Entscheidung ({len(offen)})", ""]
        if geschuetzt:
            aus += [f"_Davon {len(geschuetzt)} durch die Schutzregeln "
                    "vom Loeschen zurueckgehalten._", ""]
        zeilen = []
        for e in offen[:max_pruefen]:
            zeilen.append([
                f"{e.get('datum', '')[:10]}",
                _kuerzen(e.get("absender") or e.get("absender_adresse", ""), 28),
                _kuerzen(e.get("betreff", ""), 46),
                e["kategorie"],
            ])
        aus += _tabelle(["Datum", "Von", "Betreff", "Kategorie"], zeilen)
        rest = len(offen) - min(len(offen), max_pruefen)
        if rest > 0:
            aus += ["", f"_… und {rest} weitere. "
                    "Vollstaendig in der JSON-Datei zu diesem Lauf._"]

    # Stichproben je Aktion, damit man den Vorschlag pruefen kann,
    # ohne alles zu lesen.
    aus += ["", "## Stichproben", ""]
    for aktion in AKTION_REIHENFOLGE:
        if aktion in PASSIVE_AKTIONEN or not nach_aktion.get(aktion):
            continue
        beispiele = [e for e in eintraege if e["aktion"] == aktion][:max_beispiele]
        aus += [f"**{aktion}** ({nach_aktion[aktion]}):"]
        for e in beispiele:
            aus.append(
                f"- {_kuerzen(e.get('absender') or e.get('absender_adresse', ''), 30)}"
                f" — {_kuerzen(e.get('betreff', ''), 56)}"
                f"  `{e.get('regel', '')}`"
            )
        aus.append("")

    if len(aus) > max_zeilen:
        behalten = aus[: max_zeilen - 2]
        behalten += ["", f"_… Bericht bei {max_zeilen} Zeilen gekappt "
                     f"({len(aus) - max_zeilen + 2} weitere). Der vollstaendige "
                     "Plan liegt als JSON daneben._"]
        aus = behalten

    return "\n".join(aus) + "\n"


def kurzfassung(eintraege: list[dict], konto: str) -> str:
    """Eine Zeile fuers Terminal - mehr braucht es beim Lauf nicht."""
    nach_aktion = Counter(e["aktion"] for e in eintraege)
    teile = [f"{nach_aktion[a]}×{a}" for a in AKTION_REIHENFOLGE if nach_aktion.get(a)]
    return f"{konto}: {len(eintraege)} Nachrichten → " + ", ".join(teile or ["nichts"])
