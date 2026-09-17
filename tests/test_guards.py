"""Die harten Sicherungen - und zwar so geprueft, dass sie wahr bleiben.

Der erste Block prueft nicht Verhalten, sondern den Quelltext selbst. Das ist
ungewoehnlich, aber hier der Punkt: Zusagen wie "versendet nie eine Mail" oder
"loescht nie endgueltig" sind nur so lange etwas wert, wie sie auch nach dem
naechsten Umbau noch gelten. Ein Test, der den Code liest, faengt das ab - eine
Notiz in der Doku nicht.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mailtriage import guards  # noqa: E402
from mailtriage.config import Konto  # noqa: E402
from mailtriage.mailbox import Mailbox  # noqa: E402
from mailtriage.model import Message  # noqa: E402
from mailtriage.rules import Entscheidung  # noqa: E402

PAKET = Path(__file__).resolve().parent.parent / "mailtriage"
QUELLEN = sorted(PAKET.glob("*.py"))
JETZT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
KONTO = Konto(name="test", host="h", benutzer="u")


def baeume():
    for pfad in QUELLEN:
        yield pfad, ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))


def alle_aufrufe():
    for pfad, baum in baeume():
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute):
                yield pfad, knoten


def alle_texte():
    for pfad, baum in baeume():
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Constant) and isinstance(knoten.value, str):
                yield pfad, knoten.value


class TestZusagenImQuelltext(unittest.TestCase):
    """Was dieses Werkzeug grundsaetzlich nicht kann."""

    def test_es_gibt_keine_versandfunktion(self):
        verboten = {"smtplib", "poplib", "email.message", "sendgrid"}
        for pfad, baum in baeume():
            for knoten in ast.walk(baum):
                namen = []
                if isinstance(knoten, ast.Import):
                    namen = [a.name for a in knoten.names]
                elif isinstance(knoten, ast.ImportFrom):
                    namen = [knoten.module or ""]
                for name in namen:
                    self.assertNotIn(
                        name, verboten,
                        f"{pfad.name} importiert {name!r} - dieses Werkzeug darf "
                        "keine Mail versenden koennen.")

    def test_keine_sende_aufrufe(self):
        verboten = {"sendmail", "send_message", "send", "reply", "forward"}
        for pfad, knoten in alle_aufrufe():
            self.assertNotIn(
                knoten.func.attr, verboten,
                f"{pfad.name}:{knoten.lineno} ruft {knoten.func.attr}() auf.")

    def test_kein_endgueltiges_loeschen(self):
        """Kein nacktes EXPUNGE, kein Ordner-DELETE, kein Papierkorb leeren."""
        for pfad, knoten in alle_aufrufe():
            self.assertNotEqual(
                knoten.func.attr, "expunge",
                f"{pfad.name}:{knoten.lineno} ruft expunge() auf - das loescht "
                "alle als geloescht markierten Nachrichten endgueltig.")
            self.assertNotEqual(
                knoten.func.attr, "delete",
                f"{pfad.name}:{knoten.lineno} ruft delete() auf.")

    def test_expunge_nur_mit_ausdruecklicher_uid_menge(self):
        """UID EXPUNGE darf nur die Nachrichten treffen, die wir selbst kopiert haben."""
        gefunden = 0
        for pfad, knoten in alle_aufrufe():
            if knoten.func.attr != "uid" or not knoten.args:
                continue
            erstes = knoten.args[0]
            if isinstance(erstes, ast.Constant) and erstes.value == "EXPUNGE":
                gefunden += 1
                self.assertGreaterEqual(
                    len(knoten.args), 2,
                    f"{pfad.name}:{knoten.lineno}: UID EXPUNGE ohne UID-Menge "
                    "wuerde den ganzen Ordner treffen.")
        self.assertEqual(gefunden, 1, "Erwartet: genau ein UID-EXPUNGE (MOVE-Ersatz)")

    def test_es_werden_nie_nachrichteninhalte_geladen(self):
        for pfad, text in alle_texte():
            if "BODY[" in text or "BODY.PEEK[" in text:
                self.assertIn("HEADER.FIELDS", text,
                              f"{pfad.name}: {text!r} laedt mehr als Kopfzeilen.")
            self.assertNotIn("RFC822.TEXT", text, f"{pfad.name}: {text!r}")
            # RFC822.SIZE ist in Ordnung (eine Zahl), nacktes RFC822 nicht.
            self.assertIsNone(
                re.search(r"\bRFC822\b(?!\.)", text),
                f"{pfad.name}: {text!r} wuerde die ganze Nachricht laden.")


class FakeIMAP:
    """Zeichnet auf, welche Kommandos tatsaechlich rausgehen."""

    def __init__(self):
        self.kommandos: list[str] = []

    def _merke(self, name, *a):
        self.kommandos.append(name)
        return ("OK", [b"1"])

    def select(self, mailbox, readonly=True):
        self.kommandos.append(f"SELECT({'ro' if readonly else 'rw'})")
        return ("OK", [b"1"])

    def close(self):
        return self._merke("CLOSE")

    def unselect(self):
        return self._merke("UNSELECT")

    def logout(self):
        return self._merke("LOGOUT")


class TestOrdnerWechselLoeschtNichts(unittest.TestCase):
    """CLOSE wuerde markierte Nachrichten endgueltig entfernen - UNSELECT nicht."""

    def baue(self, faehigkeiten):
        box = Mailbox("test", "h", 993, "u", "x")
        box._imap = FakeIMAP()
        box._capabilities = frozenset(faehigkeiten)
        return box, box._imap

    def test_wechsel_benutzt_unselect_statt_close(self):
        box, imap = self.baue({"UNSELECT", "MOVE"})
        box.select("INBOX", readonly=False)
        box.select("Archive", readonly=False)
        self.assertIn("UNSELECT", imap.kommandos)
        self.assertNotIn("CLOSE", imap.kommandos)

    def test_ohne_unselect_wird_vorher_auf_nur_lesen_gestellt(self):
        box, imap = self.baue({"MOVE"})
        box.select("INBOX", readonly=False)
        box.select("Archive", readonly=False)
        # Vor dem CLOSE muss ein lesendes SELECT stehen, sonst wird geloescht.
        self.assertIn("CLOSE", imap.kommandos)
        vor_close = imap.kommandos[:imap.kommandos.index("CLOSE")]
        self.assertEqual(vor_close[-1], "SELECT(ro)")

    def test_abmelden_loescht_nichts(self):
        box, imap = self.baue({"UNSELECT"})
        box.select("INBOX", readonly=False)
        box.close()
        self.assertNotIn("CLOSE", imap.kommandos)
        self.assertIn("LOGOUT", imap.kommandos)


class TestGesperrteOrdner(unittest.TestCase):
    def test_systemordner_werden_nie_gelesen(self):
        for ordner in ["Sent", "Sent Messages", "Gesendete Objekte", "Entwuerfe",
                       "Entwurf", "Papierkorb", "Deleted Messages", "Junk",
                       "Junk E-Mail", "Spam", "Trash"]:
            with self.assertRaises(guards.GuardError, msg=ordner):
                guards.pruefe_quellordner(ordner)

    def test_normale_ordner_sind_erlaubt(self):
        for ordner in ["INBOX", "Archive", "Archiv/Immobilien", "Triage/1 Handeln",
                       "Kunden/Meier", "Gesendete Angebote 2024"]:
            guards.pruefe_quellordner(ordner)


class TestMindestalter(unittest.TestCase):
    def msg(self, tage, **kw):
        basis = dict(account="t", folder="INBOX", uid=1,
                     date=JETZT - timedelta(days=tage), size=100)
        basis.update(kw)
        return Message(**basis)

    def ent(self, aktion="loeschen"):
        return Entscheidung(kategorie="newsletter", aktion=aktion,
                            regel="Testregel", zielordner="Papierkorb")

    def test_frische_mail_wird_nie_geloescht(self):
        e = guards.erzwinge_mindestalter(self.ent(), self.msg(3), JETZT, 30)
        self.assertEqual(e.aktion, "pruefen")
        self.assertIsNone(e.zielordner)
        self.assertIn("juenger als 30", e.schutz)

    def test_alte_mail_darf_geloescht_werden(self):
        e = guards.erzwinge_mindestalter(self.ent(), self.msg(90), JETZT, 30)
        self.assertEqual(e.aktion, "loeschen")

    def test_genau_an_der_grenze_ist_erlaubt(self):
        e = guards.erzwinge_mindestalter(self.ent(), self.msg(30), JETZT, 30)
        self.assertEqual(e.aktion, "loeschen")

    def test_frischer_massenversand_darf_in_den_spam_ordner(self):
        e = guards.erzwinge_mindestalter(
            self.ent("spam"), self.msg(1, has_unsubscribe=True), JETZT, 30)
        self.assertEqual(e.aktion, "spam")

    def test_frische_echte_post_kommt_nie_in_den_spam_ordner(self):
        e = guards.erzwinge_mindestalter(self.ent("spam"), self.msg(1), JETZT, 30)
        self.assertEqual(e.aktion, "pruefen")

    def test_harmlose_aktionen_bleiben_unberuehrt(self):
        for aktion in ("archivieren", "handeln", "lesen", "pruefen"):
            e = guards.erzwinge_mindestalter(self.ent(aktion), self.msg(1), JETZT, 30)
            self.assertEqual(e.aktion, aktion)

    def test_keine_regel_kann_die_grenze_aushebeln(self):
        """Auch eine Regel, die ausdruecklich loeschen will, kommt nicht vorbei."""
        from mailtriage.rules import klassifiziere
        regeln = [{"name": "Alles weg", "wenn": {},
                   "dann": {"kategorie": "spam", "aktion": "loeschen"}}]
        e = klassifiziere(self.msg(2), regeln, {}, {}, KONTO, JETZT)
        self.assertEqual(e.aktion, "loeschen")          # Regelwerk sagt loeschen
        e = guards.erzwinge_mindestalter(e, self.msg(2), JETZT, 30)
        self.assertEqual(e.aktion, "pruefen")           # Sicherung sagt nein


class TestEingewoehnungsmodus(unittest.TestCase):
    def test_nichts_destruktives_kommt_durch(self):
        for aktion in ("loeschen", "spam"):
            e = guards.ohne_loeschen(Entscheidung(
                kategorie="newsletter", aktion=aktion, regel="R",
                zielordner="Papierkorb"))
            self.assertEqual(e.aktion, "pruefen")
            self.assertIsNone(e.zielordner)

    def test_archivieren_bleibt_erlaubt(self):
        e = guards.ohne_loeschen(Entscheidung(
            kategorie="newsletter", aktion="archivieren", regel="R",
            zielordner="Archive"))
        self.assertEqual(e.aktion, "archivieren")


class TestNotbremse(unittest.TestCase):
    def eintraege(self, n, aktion, regel):
        return [{"aktion": aktion, "regel": regel} for _ in range(n)]

    def test_eine_regel_raeumt_fast_alles_weg(self):
        grund = guards.notbremse(self.eintraege(200, "loeschen", "Kaputte Regel")
                                 + self.eintraege(5, "archivieren", "X"))
        self.assertIn("Notbremse", grund)
        self.assertIn("Kaputte Regel", grund)

    def test_viele_verschiedene_regeln_sind_normal(self):
        """Eine alte Woche voller Newsletter darf komplett weggeraeumt werden."""
        eintraege = []
        for i in range(10):
            eintraege += self.eintraege(30, "loeschen", f"Regel {i}")
        self.assertEqual(guards.notbremse(eintraege), "")

    def test_kleine_laeufe_loesen_nie_aus(self):
        self.assertEqual(
            guards.notbremse(self.eintraege(50, "loeschen", "Eine Regel")), "")

    def test_normaler_lauf_loest_nicht_aus(self):
        eintraege = (self.eintraege(100, "loeschen", "Newsletter alt")
                     + self.eintraege(100, "archivieren", "Rechnungen")
                     + self.eintraege(50, "pruefen", "Standard"))
        self.assertEqual(guards.notbremse(eintraege), "")


class TestNurLesen(unittest.TestCase):
    def test_konto_mit_nur_lesen_wird_nie_veraendert(self):
        with self.assertRaises(guards.GuardError):
            guards.pruefe_schreibrecht(Konto(name="firma", host="h", benutzer="u",
                                             nur_lesen=True))

    def test_normales_konto_darf_schreiben(self):
        guards.pruefe_schreibrecht(Konto(name="icloud", host="h", benutzer="u"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
