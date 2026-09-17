"""Einrichtungsassistent: von null bis zum ersten Bericht.

Fragt die Postfaecher ab, legt die Passwoerter im Schluesselbund ab, testet
die Verbindung, legt die Ordner an und macht den ersten Lauf. Alles, was man
sonst aus drei Dokumentationsseiten zusammensuchen muesste.
"""

from __future__ import annotations

import getpass
import json
import platform
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

from .config import CONFIG_DIR, ConfigError

# Bekannte Anbieter - erspart das Suchen in den Apple-Mail-Einstellungen.
ANBIETER = {
    "1": ("Microsoft 365 / Exchange Online", "outlook.office365.com"),
    "2": ("IONOS", "imap.ionos.de"),
    "3": ("Strato", "imap.strato.de"),
    "4": ("All-Inkl", "imap.all-inkl.com"),
    "5": ("Google Workspace", "imap.gmail.com"),
    "6": ("Mailbox.org", "imap.mailbox.org"),
    "7": ("anderer / selbst eintragen", ""),
}


def _ist_macos() -> bool:
    return platform.system() == "Darwin"


def frage(text: str, standard: str = "") -> str:
    zusatz = f" [{standard}]" if standard else ""
    try:
        antwort = input(f"  {text}{zusatz}: ").strip()
    except EOFError:
        return standard
    return antwort or standard


def frage_ja(text: str, standard: bool = True) -> bool:
    vorgabe = "J/n" if standard else "j/N"
    try:
        antwort = input(f"  {text} [{vorgabe}]: ").strip().lower()
    except EOFError:
        return standard
    if not antwort:
        return standard
    return antwort.startswith("j")


def ins_schluesselbund(dienst: str, konto: str, passwort: str) -> bool:
    """True, wenn es im Schluesselbund liegt."""
    if not _ist_macos() or not shutil.which("security"):
        return False
    ergebnis = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", dienst,
         "-a", konto, "-w", passwort],
        capture_output=True, text=True, check=False,
    )
    return ergebnis.returncode == 0


def _ueberschrift(text: str) -> None:
    print(f"\n{text}\n" + "─" * min(len(text), 64))


def konfiguration_anlegen() -> tuple[Path, Path]:
    """Kopiert die Vorlagen, falls die echten Dateien noch fehlen."""
    konten = CONFIG_DIR / "konten.json"
    regeln = CONFIG_DIR / "regeln.json"
    for ziel in (konten, regeln):
        vorlage = ziel.with_name(ziel.stem + ".beispiel.json")
        if not ziel.exists():
            if not vorlage.exists():
                raise ConfigError(f"Vorlage fehlt: {vorlage}")
            ziel.write_text(vorlage.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  angelegt: {ziel.relative_to(CONFIG_DIR.parent)}")
    return konten, regeln


def konto_abfragen(roh: dict, name: str) -> tuple[dict, str | None]:
    """Fragt ein Konto ab. Gibt (Konto-Eintrag, Passwort oder None) zurueck."""
    eintrag = next((k for k in roh["konten"] if k.get("name") == name), None)
    if eintrag is None:
        return {}, None

    beschreibung = eintrag.get("beschreibung", name)
    _ueberschrift(f"Postfach: {beschreibung}")

    if name == "icloud":
        adresse = frage("E-Mail-Adresse",
                        (eintrag.get("meine_adressen") or [""])[0])
        eintrag["meine_adressen"] = [adresse] if adresse else []
        eintrag["benutzer"] = frage(
            "IMAP-Benutzername (bei iCloud meist der Teil vor dem @)",
            adresse.split("@")[0] if adresse else eintrag.get("benutzer", ""))
        print("\n  Fuer iCloud brauchst du ein app-spezifisches Passwort.")
        print("  account.apple.com → Anmeldung und Sicherheit →")
        print("  App-spezifische Passwoerter → neues erzeugen.")
        print("  Das normale Apple-ID-Passwort funktioniert bei IMAP nicht.\n")
    else:
        if not frage_ja("Dieses Postfach jetzt einrichten?", True):
            eintrag["aktiv"] = False
            print("  uebersprungen - spaeter in config/konten.json auf "
                  '"aktiv": true stellen.')
            return eintrag, None

        adresse = frage("E-Mail-Adresse", eintrag.get("benutzer", ""))
        eintrag["meine_adressen"] = [adresse] if adresse else []
        eintrag["benutzer"] = adresse
        eintrag["aktiv"] = True

        print("\n  Wer betreibt das Postfach?")
        for schluessel, (bezeichnung, host) in ANBIETER.items():
            print(f"    {schluessel}) {bezeichnung}" + (f"  ({host})" if host else ""))
        wahl = frage("Auswahl", "1")
        _, host = ANBIETER.get(wahl, ANBIETER["7"])
        if not host:
            print("\n  Den IMAP-Server findest du in Apple Mail unter")
            print("  Einstellungen → Accounts → Servereinstellungen.")
            host = frage("IMAP-Server", eintrag.get("host", ""))
        eintrag["host"] = host
        print(f"  Server: {host}")

    dienst = eintrag.get("keychain_dienst") or f"mailtriage-{name}"
    eintrag["keychain_dienst"] = dienst

    try:
        passwort = getpass.getpass(f"  Passwort fuer {eintrag['benutzer']} "
                                   "(Eingabe bleibt unsichtbar): ").strip()
    except EOFError:
        passwort = ""
    if not passwort:
        print("  kein Passwort eingegeben - uebersprungen.")
        return eintrag, None

    if ins_schluesselbund(dienst, eintrag["benutzer"], passwort):
        print("  im Schluesselbund gespeichert.")
    else:
        variable = f"MAILTRIAGE_{name.upper()}_PASSWORT"
        print("  Schluesselbund nicht verfuegbar. Setze stattdessen:")
        print(f"    export {variable}='<passwort>'")
    return eintrag, passwort


def verbindung_testen(cfg, konto_name: str) -> bool:
    from .mailbox import Mailbox, MailboxError
    konto = cfg.konto(konto_name)
    try:
        passwort = konto.passwort()
    except ConfigError as exc:
        print(f"  {exc}")
        return False
    try:
        with Mailbox(konto.name, konto.host, konto.port, konto.benutzer,
                     passwort, verbose=False) as box:
            ordner = box.folders()
            print(f"  Verbindung steht – {len(ordner['alle'])} Ordner gefunden.")
            for rolle in ("archiv", "papierkorb", "spam"):
                gefunden = ordner.get(rolle)
                if gefunden:
                    konto.ordner[rolle] = gefunden[0]
                    print(f"    {rolle}: {gefunden[0]}")
            for rolle in ("handeln", "wartet", "lesen"):
                ziel = konto.ordner_fuer(rolle)
                neu = box.ensure_folder(ziel)
                print(f"    {ziel} {'(angelegt)' if neu else '(vorhanden)'}")
        return True
    except MailboxError as exc:
        print(f"  Verbindung fehlgeschlagen:\n    {exc}")
        return False


def montag_dieser_woche(heute: date | None = None) -> date:
    heute = heute or date.today()
    return heute - timedelta(days=heute.weekday())


def start(args, _cfg=None) -> int:
    from . import config as config_modul

    print("Einrichtung der E-Mail-Triage")
    print("Du kannst jederzeit mit Strg-C abbrechen; nichts wird veraendert,")
    print("solange du am Ende nicht ausdruecklich zustimmst.")

    _ueberschrift("1. Konfigurationsdateien")
    konten_pfad, _ = konfiguration_anlegen()
    roh = json.loads(konten_pfad.read_text(encoding="utf-8"))

    for name in [k.get("name") for k in roh["konten"]]:
        eintrag, _ = konto_abfragen(roh, name)
        if eintrag:
            for i, k in enumerate(roh["konten"]):
                if k.get("name") == name:
                    roh["konten"][i] = eintrag
    konten_pfad.write_text(json.dumps(roh, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"\n  gespeichert: {konten_pfad}")

    _ueberschrift("2. Verbindung und Ordner")
    try:
        cfg = config_modul.lade(konten_pfad)
    except ConfigError as exc:
        print(f"  {exc}")
        return 2

    erreichbar = []
    for konto in cfg.aktive_konten():
        print(f"\n  {konto.name} ({konto.host})")
        if verbindung_testen(cfg, konto.name):
            erreichbar.append(konto.name)

    if not erreichbar:
        print("\nKein Postfach erreichbar. Bitte Angaben pruefen und")
        print("  python3 -m mailtriage start")
        print("noch einmal aufrufen.")
        return 1

    montag = montag_dieser_woche()
    _ueberschrift("3. Erster Lauf")
    print(f"  Gescannt wird ab Montag, {montag.strftime('%d.%m.%Y')}.")
    print("  Der Lauf liest nur und schreibt einen Vorschlag - er")
    print("  veraendert nichts in deinen Postfaechern.\n")

    if not frage_ja("Jetzt scannen?", True):
        print("\n  Abgebrochen. Wenn du soweit bist:")
        print(f"    python3 -m mailtriage morgens --seit {montag.isoformat()} "
              "--ohne-loeschen")
        return 0

    from .cli import befehl_scannen

    class ScanArgs:
        konto = erreichbar
        leise = False
        seit = montag
        ohne_loeschen = True
        trotzdem = False
        wochen = 1

    ergebnis = befehl_scannen(ScanArgs(), cfg, "taeglich")

    _ueberschrift("Fertig")
    print("  Die Berichte liegen in runs/ - lies sie durch.")
    print("  Wenn der Vorschlag passt:")
    print("    python3 -m mailtriage anwenden          # zeigt, was passieren wuerde")
    print("    python3 -m mailtriage anwenden --ja     # fuehrt es aus")
    print("\n  Falls etwas schiefgeht:")
    print("    python3 -m mailtriage rueckgaengig --ja")
    return ergebnis
