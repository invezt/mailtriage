"""Der Produktionscode gegen einen echten IMAP-Server ueber echtes TLS.

Die uebrigen Tests ersetzen die Mailbox durch eine Attrappe. Hier laeuft die
echte Klasse mit echtem imaplib ueber einen echten Socket. Das prueft genau
die Stellen, die eine Attrappe nicht pruefen kann: Literale in der
FETCH-Antwort, UTF-7 auf dem Draht, UNSELECT statt CLOSE, neue UIDs nach MOVE.
"""

from __future__ import annotations

import os
import ssl
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from imap_testserver import Nachricht, starte_server  # noqa: E402

from mailtriage.mailbox import Mailbox  # noqa: E402


def kopf(betreff: str, von: str = "Absender <a@example.com>") -> bytes:
    return (f"From: {von}\r\nTo: ich@example.com\r\n"
            f"Subject: {betreff}\r\n\r\n").encode("utf-8")


class EchterServerTest(unittest.TestCase):
    """Basis: startet einen Server und laesst das Zertifikat vertrauen."""

    server_optionen: dict = {}

    def setUp(self):
        self.server, self.tmp, cert = starte_server(**self.server_optionen)
        # ssl.create_default_context() liest SSL_CERT_FILE - so vertraut der
        # Produktionscode dem Testzertifikat, ohne dass er angefasst wird.
        self._alt = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = str(cert)
        ssl._create_default_https_context = ssl.create_default_context

        self.server.fuelle("INBOX", [
            Nachricht(1, "14-Sep-2026 09:15:00 +0200", "\\Seen",
                      kopf("Rueckfrage zum Projekt")),
            Nachricht(2, "15-Sep-2026 11:00:00 +0200", "",
                      kopf("Newsletter KW38", "News <news@shop.de>")),
            Nachricht(3, "16-Sep-2026 17:42:00 +0200", "\\Seen \\Flagged",
                      kopf("Wichtig: Nebenkosten")),
            Nachricht(4, "01-Mar-2019 08:00:00 +0100", "\\Seen",
                      kopf("Uralte Mail")),
        ])

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()
        if self._alt is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = self._alt

    def box(self) -> Mailbox:
        return Mailbox("test", "127.0.0.1", self.server.port, "u", "geheim")


class TestVerbindungUndOrdner(EchterServerTest):
    def test_anmeldung_und_faehigkeiten(self):
        with self.box() as box:
            self.assertTrue(box.has("MOVE"))
            self.assertTrue(box.has("UNSELECT"))
            self.assertFalse(box.has("GIBTESNICHT"))

    def test_falsches_passwort_gibt_verstaendlichen_fehler(self):
        from mailtriage.mailbox import MailboxError
        box = Mailbox("test", "127.0.0.1", self.server.port, "u", "falsch")
        with self.assertRaises(MailboxError) as ctx:
            box.connect(retries=1)
        self.assertIn("app-spezifisches Passwort", str(ctx.exception))

    def test_sonderordner_werden_erkannt(self):
        with self.box() as box:
            ordner = box.folders()
            self.assertIn("INBOX", ordner["alle"])
            self.assertEqual(ordner.get("archiv"), ["Archive"])
            self.assertEqual(ordner.get("papierkorb"), ["Deleted Messages"])
            self.assertEqual(ordner.get("spam"), ["Junk"])

    def test_ordner_anlegen(self):
        with self.box() as box:
            self.assertTrue(box.ensure_folder("Triage/1 Handeln"))
            self.assertIn("Triage/1 Handeln", self.server.angelegt)
            self.assertFalse(box.ensure_folder("Triage/1 Handeln"))


class TestLesen(EchterServerTest):
    def test_kopfzeilen_werden_korrekt_gelesen(self):
        with self.box() as box:
            uids = box.search_window("INBOX")
            self.assertEqual(uids, [1, 2, 3, 4])
            msgs = {m.uid: m for m in box.fetch_headers("INBOX", uids)}

            self.assertEqual(len(msgs), 4)
            self.assertEqual(msgs[1].subject, "Rueckfrage zum Projekt")
            self.assertEqual(msgs[2].from_addr, "news@shop.de")
            self.assertEqual(msgs[1].date,
                             datetime(2026, 9, 14, 7, 15, tzinfo=timezone.utc))
            self.assertGreater(msgs[1].size, 0)

    def test_flags_kommen_an(self):
        """Wenn FLAGS verlorengehen, greift der Schutz markierter Mails nicht mehr."""
        with self.box() as box:
            msgs = {m.uid: m for m in
                    box.fetch_headers("INBOX", box.search_window("INBOX"))}
            self.assertTrue(msgs[1].seen)
            self.assertFalse(msgs[2].seen)
            self.assertTrue(msgs[3].flagged, "markierte Mail nicht als markiert erkannt")
            self.assertFalse(msgs[1].flagged)

    def test_zeitfenster_wird_serverseitig_gefiltert(self):
        with self.box() as box:
            uids = box.search_window(
                "INBOX",
                since=datetime(2026, 9, 14, tzinfo=timezone.utc),
                before=datetime(2026, 9, 16, tzinfo=timezone.utc))
            self.assertEqual(uids, [1, 2])

    def test_nur_ungelesene(self):
        with self.box() as box:
            self.assertEqual(box.search_window("INBOX", unseen_only=True), [2])


class TestFlagsNachLiteral(EchterServerTest):
    """Manche Server liefern FLAGS erst nach dem BODY-Literal."""

    server_optionen = {"flags_nach_literal": True}

    def test_flags_werden_auch_dann_gefunden(self):
        with self.box() as box:
            msgs = {m.uid: m for m in
                    box.fetch_headers("INBOX", box.search_window("INBOX"))}
            self.assertTrue(msgs[3].flagged,
                            "FLAGS nach dem Literal wurden nicht gelesen - "
                            "der Schutz markierter Mails waere wirkungslos")
            self.assertTrue(msgs[1].seen)
            self.assertFalse(msgs[2].seen)


class TestVerschieben(EchterServerTest):
    def test_verschieben_mit_move(self):
        with self.box() as box:
            self.assertEqual(box.move("INBOX", [2, 4], "Deleted Messages"), 2)
        verbleibend = [n.uid for n in self.server.ordner["INBOX"]]
        self.assertEqual(verbleibend, [1, 3])
        self.assertEqual(len(self.server.ordner["Deleted Messages"]), 2)

    def test_verschieben_in_ordner_mit_umlaut(self):
        self.server.ordner["Gelöschte Objekte"] = []
        with self.box() as box:
            box.move("INBOX", [4], "Gelöschte Objekte")
        self.assertEqual(len(self.server.ordner["Gelöschte Objekte"]), 1)

    def test_in_denselben_ordner_passiert_nichts(self):
        with self.box() as box:
            self.assertEqual(box.move("INBOX", [1], "INBOX"), 0)
        self.assertEqual(len(self.server.ordner["INBOX"]), 4)


class TestOhneMove(EchterServerTest):
    """Server ohne MOVE: COPY + STORE + UID EXPUNGE als Ersatz."""

    server_optionen = {"kann_move": False}

    def test_ersatzweg_wird_benutzt(self):
        with self.box() as box:
            self.assertFalse(box.has("MOVE"))
            box.move("INBOX", [2], "Archive")
        self.assertIn("UID COPY", self.server.protokoll)
        self.assertIn("UID STORE", self.server.protokoll)
        self.assertIn("UID EXPUNGE", self.server.protokoll)


class TestOrdnerWechsel(EchterServerTest):
    def test_unselect_statt_close(self):
        with self.box() as box:
            box.select("INBOX", readonly=False)
            box.select("Archive", readonly=False)
        self.assertIn("UNSELECT", self.server.protokoll)
        self.assertNotIn("CLOSE", self.server.protokoll)


class TestOhneUnselect(EchterServerTest):
    """Server ohne UNSELECT: vorher auf nur-lesend stellen, dann ist CLOSE harmlos."""

    server_optionen = {"kann_unselect": False}

    def test_close_erst_nach_lesendem_select(self):
        with self.box() as box:
            self.assertFalse(box.has("UNSELECT"))
            box.select("INBOX", readonly=False)
            box.select("Archive", readonly=False)
        eintraege = self.server.protokoll
        self.assertIn("CLOSE", eintraege)
        # Direkt vor dem CLOSE muss ein EXAMINE stehen (nur lesend).
        self.assertEqual(eintraege[eintraege.index("CLOSE") - 1], "EXAMINE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
