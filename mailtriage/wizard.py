"""Einrichtungsassistent: von null bis zum ersten Bericht.

Fragt die Postfaecher ab, legt die Passwoerter im Schluesselbund ab, testet
die Verbindung, legt die Ordner an und macht den ersten Lauf. Alles, was man
sonst aus drei Dokumentationsseiten zusammensuchen muesste.
"""

from __future__ import annotations

import getpass
import json
import re
import platform
import shutil
import subprocess
import sys
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


def eingabepuffer_leeren() -> None:
    """Wartende Tastatureingaben verwerfen.

    Wer mehrere Befehle auf einmal in das Terminal einfuegt, hinterlaesst
    Zeilenumbrueche im Puffer. Die laufen sonst ungefragt in den naechsten
    Prompt - und eine Passwortabfrage, die so eine leere Zeile frisst, sieht
    aus, als waere sie uebersprungen worden. Genau das ist passiert.
    """
    try:
        import termios
    except ImportError:
        return
    try:
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (termios.error, OSError, ValueError, AttributeError):
        # Kein echtes Terminal (Pipe, CI, Testlauf) - dann gibt es auch
        # keinen Puffer zu leeren. termios.error ist kein OSError.
        pass


def aus_schluesselbund(dienst: str, konto: str) -> bool:
    """Prueft, ob wirklich etwas im Schluesselbund gelandet ist."""
    if not _ist_macos() or not shutil.which("security"):
        return False
    ergebnis = subprocess.run(
        ["security", "find-generic-password", "-s", dienst, "-a", konto, "-w"],
        capture_output=True, text=True, check=False,
    )
    return ergebnis.returncode == 0 and bool(ergebnis.stdout.strip())


def passwort_aus_apple_mail(host: str, benutzer: str) -> str | None:
    """Das Passwort, das Apple Mail fuer dieses Postfach schon hinterlegt hat.

    Apple Mail legt IMAP-Zugaenge als "Internet-Passwort" im Schluesselbund
    ab. Wer Mail eingerichtet hat, hat das Passwort also laengst auf dem
    Rechner - es muss nur freigegeben werden. macOS fragt dabei einmal per
    Fenster nach; mit "Immer erlauben" ist danach Ruhe.

    Gibt None zurueck, wenn nichts gefunden wurde oder die Freigabe
    verweigert wurde. Der Rueckgabewert wird nie ausgegeben.
    """
    if not _ist_macos() or not shutil.which("security"):
        return None
    for konto in (benutzer, benutzer.split("@")[0]):
        if not konto:
            continue
        try:
            ergebnis = subprocess.run(
                ["security", "find-internet-password", "-s", host,
                 "-a", konto, "-w"],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if ergebnis.returncode == 0 and ergebnis.stdout.strip():
            return ergebnis.stdout.strip()
    return None


def _applescript_text(text: str) -> str:
    """Text so einpacken, dass AppleScript ihn unveraendert nimmt."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def passwort_dialog(titel: str, text: str) -> str:
    """Natives macOS-Fenster zur Passworteingabe.

    Damit laesst sich das Passwort auch dann hinterlegen, wenn gar kein
    Terminal im Spiel ist - etwa wenn der Befehl aus der Claude-Desktop-App
    heraus laeuft. Die Eingabe geht direkt von diesem Fenster in den
    Schluesselbund; sie wird nirgends ausgegeben und steht auch nicht im
    AppleScript, also nicht in der Prozessliste.
    """
    if not _ist_macos() or not shutil.which("osascript"):
        return ""
    skript = (
        f"display dialog {_applescript_text(text)}"
        f" with title {_applescript_text(titel)}"
        ' default answer "" with hidden answer'
        ' buttons {"Abbrechen", "Speichern"} default button "Speichern"'
        ' with icon note'
    )
    try:
        ergebnis = subprocess.run(["osascript", "-e", skript],
                                  capture_output=True, text=True, timeout=300,
                                  check=False)
    except (subprocess.SubprocessError, OSError):
        return ""
    if ergebnis.returncode != 0:          # Abbrechen oder Fenster geschlossen
        return ""
    treffer = re.search(r"text returned:(.*)\Z", ergebnis.stdout.strip(), re.S)
    return treffer.group(1).strip() if treffer else ""


def passwort_erfragen(anzeigename: str, hinweis: str = "") -> str:
    """Passwort holen - per Dialogfenster, sonst ueber das Terminal."""
    text = f"Passwort fuer {anzeigename}"
    if hinweis:
        text += f"\n\n{hinweis}"
    passwort = passwort_dialog("E-Mail-Triage", text)
    if passwort:
        return passwort
    if not sys.stdin.isatty():
        return ""
    eingabepuffer_leeren()
    try:
        return getpass.getpass(
            f"  Passwort fuer {anzeigename} (unsichtbar, dann Enter): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


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

    if aus_schluesselbund(dienst, eintrag["benutzer"]):
        if not frage_ja("Im Schluesselbund liegt schon ein Passwort. Ersetzen?", False):
            print("  vorhandenes Passwort wird weiter benutzt.")
            return eintrag, ""

    hinweis = ("Bei iCloud das app-spezifische Passwort von account.apple.com, "
               "nicht das Apple-ID-Passwort.") if name == "icloud" else ""
    passwort = ""
    for versuch in range(3):
        passwort = passwort_erfragen(eintrag["benutzer"], hinweis)
        if passwort:
            break
        if versuch < 2 and sys.stdin.isatty():
            print("  Nichts angekommen. Noch einmal.")
        else:
            break

    if not passwort:
        variable = f"MAILTRIAGE_{name.upper()}_PASSWORT"
        print("\n  Ohne Passwort geht es nicht weiter. Du kannst es auch")
        print("  selbst hinterlegen, dann sieht es niemand ausser dir:")
        print(f"    security add-generic-password -U -s {dienst} \\")
        print(f"      -a {eintrag['benutzer']} -w")
        print(f"  (oder: export {variable}='<passwort>')")
        return eintrag, None

    if not ins_schluesselbund(dienst, eintrag["benutzer"], passwort):
        variable = f"MAILTRIAGE_{name.upper()}_PASSWORT"
        print("  Schluesselbund nicht verfuegbar. Setze stattdessen:")
        print(f"    export {variable}='<passwort>'")
        return eintrag, passwort

    if aus_schluesselbund(dienst, eintrag["benutzer"]):
        print("  im Schluesselbund gespeichert und geprueft.")
    else:
        print("  WARNUNG: Speichern gemeldet, aber nicht wiederauffindbar.")
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


def passwoerter(args, cfg=None) -> int:
    """Passwoerter hinterlegen - ohne Terminaleingabe, per Dialogfenster.

    Gedacht fuer den Fall, dass der Befehl aus einer Oberflaeche heraus
    laeuft. Das Passwort geht vom Fenster direkt in den Schluesselbund und
    wird nie ausgegeben.
    """
    from . import config as config_modul

    try:
        cfg = cfg or config_modul.lade()
    except ConfigError as exc:
        print(f"Konfiguration fehlt:\n  {exc}")
        print("\nErst einrichten:  python3 -m mailtriage start")
        return 2

    gewuenscht = getattr(args, "konto", None)
    konten = [k for k in cfg.konten
              if not gewuenscht or k.name in gewuenscht]
    if not konten:
        print("Kein passendes Konto in der Konfiguration.")
        return 1

    if not _ist_macos():
        print("Das Dialogfenster gibt es nur auf macOS.")

    fehler = 0
    for konto in konten:
        dienst = konto.keychain_dienst or f"mailtriage-{konto.name}"
        print(f"\n{konto.name} ({konto.benutzer})")

        if aus_schluesselbund(dienst, konto.benutzer):
            if not getattr(args, "ersetzen", False):
                print("  Passwort liegt bereits im Schluesselbund. "
                      "Zum Ersetzen: --ersetzen")
                continue

        # Zuerst nachsehen, ob Apple Mail das Passwort schon hat. Dann muss
        # nichts getippt werden - nur einmal die Freigabe bestaetigt.
        print("  Suche das Passwort, das Apple Mail hinterlegt hat \u2026")
        print("  (macOS fragt gleich nach der Freigabe \u2013 "
              "am besten \"Immer erlauben\")")
        passwort = passwort_aus_apple_mail(konto.host, konto.benutzer)

        if passwort:
            print("  Gefunden \u2013 aus Apple Mail uebernommen, nichts zu tippen.")
        else:
            hinweis = ("Bei iCloud das app-spezifische Passwort von "
                       "account.apple.com, nicht das Apple-ID-Passwort."
                       if konto.name == "icloud" else "")
            print("  Nicht gefunden. Ein Fenster fragt jetzt danach.")
            passwort = passwort_erfragen(konto.benutzer, hinweis)

        if not passwort:
            print("  Abgebrochen, nichts gespeichert.")
            fehler += 1
            continue

        if not ins_schluesselbund(dienst, konto.benutzer, passwort):
            print(f"  Speichern fehlgeschlagen. Setze ersatzweise "
                  f"MAILTRIAGE_{konto.name.upper()}_PASSWORT.")
            fehler += 1
            continue

        if aus_schluesselbund(dienst, konto.benutzer):
            print("  Im Schluesselbund gespeichert und geprueft.")
        else:
            print("  WARNUNG: gespeichert gemeldet, aber nicht wiederauffindbar.")
            fehler += 1

    if not fehler:
        print("\nJetzt pruefen:  python3 -m mailtriage einrichten --anlegen")
    return 1 if fehler else 0
