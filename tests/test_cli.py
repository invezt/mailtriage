"""Die Kommandozeile - dass es die Optionen wirklich gibt.

Klingt banal, war es aber nicht: Die Scan-Optionen hingen zwischenzeitlich nur
an einem von drei Befehlen, waehrend die Doku sie fuer alle drei empfahl. Ein
Fehler, der erst beim Tippen auffaellt - also hier festgehalten.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mailtriage.cli import baue_parser  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
SCAN_BEFEHLE = ["morgens", "nachmittags", "backlog"]


def alle_befehle() -> list[str]:
    """Aus dem Parser ableiten statt pflegen - sonst driftet die Liste."""
    for aktion in baue_parser()._subparsers._group_actions:
        if hasattr(aktion, "choices"):
            return sorted(aktion.choices)
    raise AssertionError("keine Unterbefehle gefunden")


ALLE_BEFEHLE = alle_befehle()


def optionen(befehl: str) -> set[str]:
    puffer = io.StringIO()
    parser = baue_parser()
    with contextlib.redirect_stdout(puffer), contextlib.suppress(SystemExit):
        parser.parse_args([befehl, "--help"])
    return set(re.findall(r"--[a-z][a-z-]+", puffer.getvalue()))


class TestBefehle(unittest.TestCase):
    def test_alle_befehle_existieren(self):
        self.assertGreaterEqual(len(ALLE_BEFEHLE), 8)
        for befehl in ALLE_BEFEHLE:
            self.assertIn("--help", optionen(befehl), f"{befehl} fehlt")

    def test_die_erwarteten_befehle_sind_dabei(self):
        for befehl in SCAN_BEFEHLE + ["start", "anwenden", "rueckgaengig",
                                      "status", "einrichten", "kategorien"]:
            self.assertIn(befehl, ALLE_BEFEHLE)

    def test_scan_befehle_haben_alle_scan_optionen(self):
        for befehl in SCAN_BEFEHLE:
            vorhanden = optionen(befehl)
            for option in ("--seit", "--ohne-loeschen", "--konto", "--leise"):
                self.assertIn(option, vorhanden, f"{befehl} kennt {option} nicht")

    def test_backlog_befehle_koennen_mehrere_wochen(self):
        for befehl in ("nachmittags", "backlog"):
            self.assertIn("--wochen", optionen(befehl))

    def test_ausfuehrende_befehle_brauchen_ja(self):
        for befehl in ("anwenden", "rueckgaengig"):
            self.assertIn("--ja", optionen(befehl),
                          f"{befehl} wuerde ohne Bestaetigung laufen")

    def test_ohne_ja_ist_nichts_scharf(self):
        for befehl in ("anwenden", "rueckgaengig"):
            args = baue_parser().parse_args([befehl])
            self.assertFalse(args.ja, f"{befehl} ist ohne --ja scharf")

    def test_seit_nimmt_isodatum(self):
        args = baue_parser().parse_args(["morgens", "--seit", "2026-09-14"])
        self.assertEqual(args.seit, date(2026, 9, 14))

    def test_seit_weist_deutsches_datum_verstaendlich_ab(self):
        puffer = io.StringIO()
        with contextlib.redirect_stderr(puffer), self.assertRaises(SystemExit):
            baue_parser().parse_args(["morgens", "--seit", "14.09.2026"])
        self.assertIn("JJJJ-MM-TT", puffer.getvalue())


class TestDokumentationStimmtMitDerCliUeberein(unittest.TestCase):
    """Jeder in der Doku gezeigte Befehl muss auch wirklich existieren."""

    def test_beworbene_befehle_gibt_es(self):
        aufrufe = set()
        for pfad in list((WURZEL / "docs").glob("*.md")) + [WURZEL / "README.md"]:
            for treffer in re.findall(r"python3 -m mailtriage ([a-z-]+)([^\n`]*)",
                                      pfad.read_text(encoding="utf-8")):
                aufrufe.add((treffer[0], treffer[1].strip(), pfad.name))

        for befehl, rest, quelle in sorted(aufrufe):
            self.assertIn(befehl, ALLE_BEFEHLE,
                          f"{quelle} zeigt unbekannten Befehl {befehl!r}")
            vorhanden = optionen(befehl)
            for option in re.findall(r"--[a-z][a-z-]+", rest):
                self.assertIn(option, vorhanden,
                              f"{quelle} zeigt '{befehl} {option}', "
                              f"aber {befehl} kennt {option} nicht")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestAssistent(unittest.TestCase):
    def test_montag_wird_richtig_berechnet(self):
        from mailtriage.wizard import montag_dieser_woche
        # 17.09.2026 ist ein Donnerstag, Montag war der 14.
        self.assertEqual(montag_dieser_woche(date(2026, 9, 17)), date(2026, 9, 14))
        # An einem Montag ist es der Tag selbst.
        self.assertEqual(montag_dieser_woche(date(2026, 9, 14)), date(2026, 9, 14))
        # Sonntag gehoert noch zur laufenden Woche.
        self.assertEqual(montag_dieser_woche(date(2026, 9, 20)), date(2026, 9, 14))

    def test_anbieterliste_ist_brauchbar(self):
        from mailtriage.wizard import ANBIETER
        hosts = [h for _, h in ANBIETER.values() if h]
        self.assertIn("outlook.office365.com", hosts)
        self.assertTrue(all("." in h for h in hosts))
        # Genau ein Eintrag zum Selbsteintragen.
        self.assertEqual(sum(1 for _, h in ANBIETER.values() if not h), 1)

    def test_konfiguration_wird_aus_vorlage_angelegt(self):
        import shutil
        import tempfile
        from mailtriage import wizard
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp)
            for name in ("konten", "regeln"):
                shutil.copy(WURZEL / "config" / f"{name}.beispiel.json",
                            ziel / f"{name}.beispiel.json")
            alt = wizard.CONFIG_DIR
            try:
                wizard.CONFIG_DIR = ziel
                konten, regeln = wizard.konfiguration_anlegen()
                self.assertTrue(konten.exists() and regeln.exists())
                # Zweiter Aufruf darf vorhandene Dateien nicht ueberschreiben.
                konten.write_text('{"konten": [], "markiert": true}', encoding="utf-8")
                wizard.konfiguration_anlegen()
                self.assertIn("markiert", konten.read_text(encoding="utf-8"))
            finally:
                wizard.CONFIG_DIR = alt

    def test_puffer_leeren_stuerzt_nie_ab(self):
        """Ohne Terminal (etwa in CI) muss das folgenlos durchlaufen."""
        from mailtriage.wizard import eingabepuffer_leeren
        eingabepuffer_leeren()

    def test_schluesselbund_pruefung_ohne_macos(self):
        from mailtriage.wizard import aus_schluesselbund, ins_schluesselbund
        import platform
        if platform.system() != "Darwin":
            self.assertFalse(aus_schluesselbund("mailtriage-test", "niemand"))
            self.assertFalse(ins_schluesselbund("mailtriage-test", "niemand", "x"))

    def test_passwort_funktionen_geben_nie_etwas_aus(self):
        """Ein Passwort darf nie auf stdout landen - auch nicht versehentlich."""
        import ast
        import inspect
        from mailtriage import wizard
        quelle = ast.parse(inspect.getsource(wizard))
        heikel = {"passwort_aus_apple_mail", "passwort_dialog", "passwort_erfragen"}
        for knoten in ast.walk(quelle):
            if not isinstance(knoten, ast.FunctionDef) or knoten.name not in heikel:
                continue
            for inner in ast.walk(knoten):
                if not (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id in {"print", "input"}):
                    continue
                # Ein blankes print() kann nichts verraten, ein fester Text
                # auch nicht. Gefaehrlich ist nur eine Variable im Argument.
                for arg in inner.args:
                    self.assertIsInstance(
                        arg, ast.Constant,
                        f"{knoten.name} gibt etwas Berechnetes aus - "
                        "hier koennte ein Passwort durchrutschen")

    def test_applescript_text_wird_escaped(self):
        from mailtriage.wizard import _applescript_text
        self.assertEqual(_applescript_text('a"b'), '"a\\"b"')
        self.assertEqual(_applescript_text("c\\d"), '"c\\\\d"')
        self.assertTrue(_applescript_text("x").startswith('"'))

    def test_ohne_macos_wird_kein_passwort_erfunden(self):
        import platform
        from mailtriage.wizard import passwort_aus_apple_mail, passwort_dialog
        if platform.system() != "Darwin":
            self.assertIsNone(passwort_aus_apple_mail("imap.example.com", "wer"))
            self.assertEqual(passwort_dialog("T", "Text"), "")
