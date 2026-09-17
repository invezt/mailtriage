"""Kommandozeile.

  python3 -m mailtriage morgens        # 10:00 - nur das Neue
  python3 -m mailtriage nachmittags    # 16:00 - Neues + eine Woche Backlog
  python3 -m mailtriage backlog        # nur eine Woche Backlog
  python3 -m mailtriage anwenden --ja  # den letzten Vorschlag ausfuehren
  python3 -m mailtriage status         # wie weit ist der Backlog
  python3 -m mailtriage einrichten     # Verbindung testen, Ordner anlegen
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import applier, config, planner, report, state
from .config import ConfigError
from .mailbox import Mailbox, MailboxError
from .rules import pruefe_regelwerk
from .taxonomy import AKTIONEN, KATEGORIEN


def _konten(cfg: config.Config, namen: list[str] | None):
    if not namen:
        return cfg.aktive_konten()
    return [cfg.konto(n) for n in namen]


def _lauf_ausgeben(lauf: planner.Lauf) -> None:
    print("  " + report.kurzfassung(lauf.eintraege, lauf.konto))
    if lauf.bericht_pfad:
        print(f"  Bericht: {lauf.bericht_pfad}")


def befehl_scannen(args, cfg: config.Config, modus: str) -> int:
    fortschritt = state.lade()
    jetzt = datetime.now(timezone.utc)
    laeufe: list[planner.Lauf] = []
    fehler = 0

    modi = ["taeglich"] if modus == "taeglich" else (
        ["backlog"] if modus == "backlog" else ["taeglich", "backlog"])

    for konto in _konten(cfg, args.konto):
        for einzel in modi:
            # Der Backlog kann mehrere Wochen am Stueck nehmen - bei einem
            # jahrealten Rueckstand waere eine Woche pro Tag zu langsam.
            durchgaenge = getattr(args, "wochen", 1) if einzel == "backlog" else 1
            for runde in range(durchgaenge):
                status = fortschritt.fuer(konto.name)
                if einzel == "backlog" and status.backlog_fertig and not args.trotzdem:
                    print(f"\n{konto.name} – Backlog: fertig abgearbeitet. "
                          "Mit --trotzdem weiter zurueck.")
                    break

                titel = "Neues" if einzel == "taeglich" else (
                    f"Backlog (Woche {runde + 1} von {durchgaenge})"
                    if durchgaenge > 1 else "Backlog")
                print(f"\n{konto.name} – {titel}")
                try:
                    lauf = planner.scanne(konto, cfg, einzel, fortschritt,
                                          jetzt=jetzt, leise=args.leise)
                except (MailboxError, ConfigError) as exc:
                    print(f"  FEHLER: {exc}", file=sys.stderr)
                    fehler += 1
                    break

                planner.schreibe(lauf, cfg)
                _lauf_ausgeben(lauf)
                laeufe.append(lauf)

                if einzel == "backlog":
                    state.nach_backlog_lauf(status, lauf.von, len(lauf.eintraege),
                                            lauf.aeltester)
                else:
                    state.nach_taeglichem_lauf(status, len(lauf.eintraege))

    state.speichere(fortschritt)

    zu_bewegen = sum(len(l.zu_bewegen) for l in laeufe)
    print("\n" + "─" * 60)
    print(f"{len(laeufe)} Lauf/Laeufe, {zu_bewegen} Nachrichten zum Verschieben vorgeschlagen.")
    if zu_bewegen:
        print("\nBerichte lesen, dann ausfuehren mit:")
        print("  python3 -m mailtriage anwenden --ja")
    return 1 if fehler else 0


def befehl_anwenden(args, cfg: config.Config) -> int:
    plaene: list[Path] = []
    if args.plan:
        plaene = [Path(p) for p in args.plan]
    else:
        for konto in _konten(cfg, args.konto):
            pfad = planner.letzter_plan(konto=konto.name)
            if pfad:
                plaene.append(pfad)

    if not plaene:
        print("Kein offener Plan gefunden. Erst 'morgens' oder 'nachmittags' laufen lassen.")
        return 1

    fehler = 0
    for pfad in plaene:
        print(f"\n{pfad.name}")
        try:
            ergebnis = applier.wende_an(pfad, cfg, ja=args.ja,
                                        max_aktionen=args.max_aktionen,
                                        leise=args.leise)
        except (MailboxError, ConfigError) as exc:
            print(f"  FEHLER: {exc}", file=sys.stderr)
            fehler += 1
            continue
        if args.ja:
            print("  " + ergebnis.zusammenfassung())
            for ziel, anzahl in sorted(ergebnis.je_ziel.items()):
                print(f"    → {ziel}: {anzahl}")
            for meldung in ergebnis.fehler:
                print(f"    FEHLER: {meldung}", file=sys.stderr)
                fehler += 1
            if ergebnis.offen:
                print(f"  {ergebnis.offen} Nachrichten blieben ueber dem Limit. "
                      "Denselben Befehl noch einmal aufrufen.")
    if args.ja:
        print("\nHinweis: Geloeschtes liegt im Papierkorb, nicht endgueltig weg.")
    return 1 if fehler else 0


def befehl_status(args, cfg: config.Config) -> int:
    fortschritt = state.lade()
    print("Backlog-Fortschritt\n")
    for konto in cfg.aktive_konten():
        s = fortschritt.fuer(konto.name)
        von, bis = state.backlog_fenster(
            s, cfg.einstellungen.backlog_fenster_tage,
            cfg.einstellungen.taegliches_fenster_tage)
        marke = "fertig" if s.backlog_fertig else f"naechste Woche: {von} bis {bis}"
        print(f"  {konto.name}")
        print(f"    zurueckgearbeitet bis: {s.backlog_cursor or '(noch nicht gestartet)'}")
        print(f"    Wochen erledigt:       {s.wochen_erledigt}")
        print(f"    Mails gesichtet:       {s.mails_bearbeitet}")
        print(f"    aelteste gesehen:      {s.aeltester_fund or '-'}")
        print(f"    Status:                {marke}")
        print(f"    letzter taegl. Lauf:   {s.letzter_taeglicher_lauf or '-'}")
        print()
    offen = planner.letzter_plan()
    if offen:
        print(f"Offener Plan: {offen}")
    return 0


def befehl_einrichten(args, cfg: config.Config) -> int:
    probleme = 0
    for konto in _konten(cfg, args.konto):
        print(f"\n{konto.name} ({konto.beschreibung or konto.host})")
        for meldung in pruefe_regelwerk(cfg.regeln, cfg.standard, konto):
            print(f"  Regelwerk: {meldung}")
            probleme += 1
        try:
            passwort = konto.passwort()
        except ConfigError as exc:
            print(f"  {exc}")
            probleme += 1
            continue
        try:
            with Mailbox(konto.name, konto.host, konto.port, konto.benutzer,
                         passwort, verbose=False) as box:
                ordner = box.folders()
                print(f"  Verbindung: ok ({len(ordner['alle'])} Ordner)")
                print(f"  MOVE: {'ja' if box.has('MOVE') else 'nein (Fallback aktiv)'}")
                for rolle in ("archiv", "papierkorb", "spam"):
                    gefunden = ordner.get(rolle)
                    if gefunden and rolle not in konto.ordner:
                        konto.ordner[rolle] = gefunden[0]
                        print(f"  {rolle}: vom Server erkannt → {gefunden[0]}")
                for rolle in ("handeln", "wartet", "lesen"):
                    name = konto.ordner_fuer(rolle)
                    if args.anlegen:
                        neu = box.ensure_folder(name)
                        print(f"  {rolle}: {name} {'(neu angelegt)' if neu else '(vorhanden)'}")
                    else:
                        da = name in ordner["alle"]
                        print(f"  {rolle}: {name} {'(vorhanden)' if da else '(FEHLT)'}")
                        probleme += 0 if da else 1
        except MailboxError as exc:
            print(f"  FEHLER: {exc}")
            probleme += 1

    if not args.anlegen and probleme:
        print("\nFehlende Ordner anlegen:  python3 -m mailtriage einrichten --anlegen")
    return 1 if probleme else 0


def befehl_kategorien(args, cfg=None) -> int:
    print("Kategorien (worum geht es)\n")
    for name, beschreibung in KATEGORIEN.items():
        print(f"  {name:18} {beschreibung}")
    print("\nAktionen (was passiert damit)\n")
    for name, (beschreibung, rolle) in AKTIONEN.items():
        ziel = f"→ Ordner '{rolle}'" if rolle else "(bleibt liegen)"
        print(f"  {name:14} {beschreibung:52} {ziel}")
    return 0


def baue_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mailtriage",
        description="Taegliche E-Mail-Triage ueber mehrere Postfaecher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--konten-datei", type=Path, default=None)
    p.add_argument("--regel-datei", type=Path, default=None)
    sub = p.add_subparsers(dest="befehl", required=True)

    def gemeinsam(sp):
        sp.add_argument("-k", "--konto", action="append",
                        help="nur dieses Konto (mehrfach moeglich)")
        sp.add_argument("--leise", action="store_true", help="weniger Ausgabe")
        return sp

    s = gemeinsam(sub.add_parser("morgens", help="10:00 – nur neue Nachrichten"))
    s.add_argument("--trotzdem", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=lambda a, c: befehl_scannen(a, c, "taeglich"))

    s = gemeinsam(sub.add_parser("nachmittags",
                                 help="16:00 – Neues und eine Woche Backlog"))
    s.add_argument("--trotzdem", action="store_true",
                   help="Backlog weiterlaufen lassen, auch wenn er als fertig gilt")
    s.add_argument("--wochen", type=int, default=1,
                   help="wie viele Backlog-Wochen in einem Rutsch (Standard: 1)")
    s.set_defaults(fn=lambda a, c: befehl_scannen(a, c, "beides"))

    s = gemeinsam(sub.add_parser("backlog", help="nur Backlog, ohne Tagespost"))
    s.add_argument("--trotzdem", action="store_true")
    s.add_argument("--wochen", type=int, default=1,
                   help="wie viele Wochen in einem Rutsch, z.B. --wochen 12 "
                        "fuer ein Quartal Altlast")
    s.set_defaults(fn=lambda a, c: befehl_scannen(a, c, "backlog"))

    s = gemeinsam(sub.add_parser("anwenden", help="einen Vorschlag ausfuehren"))
    s.add_argument("plan", nargs="*", help="Plandatei(en); ohne Angabe der letzte offene")
    s.add_argument("--ja", action="store_true",
                   help="wirklich ausfuehren (ohne das passiert nichts)")
    s.add_argument("--max-aktionen", type=int, default=None)
    s.set_defaults(fn=befehl_anwenden)

    s = gemeinsam(sub.add_parser("status", help="Backlog-Fortschritt anzeigen"))
    s.set_defaults(fn=befehl_status)

    s = gemeinsam(sub.add_parser("einrichten",
                                 help="Verbindung pruefen, Ordner anlegen"))
    s.add_argument("--anlegen", action="store_true", help="fehlende Ordner anlegen")
    s.set_defaults(fn=befehl_einrichten)

    s = sub.add_parser("kategorien", help="Kategorien und Aktionen anzeigen")
    s.set_defaults(fn=befehl_kategorien, konto=None, leise=False, braucht_config=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = baue_parser().parse_args(argv)
    cfg = None
    if getattr(args, "braucht_config", True):
        try:
            cfg = config.lade(args.konten_datei, args.regel_datei)
        except ConfigError as exc:
            print(f"Konfigurationsfehler:\n  {exc}", file=sys.stderr)
            return 2
    try:
        return args.fn(args, cfg)
    except KeyboardInterrupt:
        print("\nAbgebrochen. Es wurde nur ausgefuehrt, was bis hier bestaetigt war.")
        return 130
