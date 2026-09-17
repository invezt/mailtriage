"""End-to-End: scannen, Plan schreiben, anwenden - mit simuliertem Postfach.

Das echte IMAP wird ersetzt, alles andere ist der Produktionscode.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mailtriage import applier, config, planner, state  # noqa: E402
from mailtriage.model import Message  # noqa: E402

JETZT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


class FakePostfach:
    """Ein Postfach im Speicher. Zaehlt mit, was angefasst wird."""

    def __init__(self, account, host, port, user, password, **kw):
        self.account = account
        self.nachrichten: dict[int, Message] = {}
        self.bewegt: list[tuple[int, str]] = []
        self.angelegte_ordner: list[str] = []
        self.move_aufrufe = 0
        self.fetch_aufrufe = 0

    # -- vom Test befuellt --
    def fuelle(self, msgs):
        for m in msgs:
            self.nachrichten[m.uid] = m
        return self

    # -- Mailbox-Schnittstelle --
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def has(self, cap):
        return cap.upper() == "MOVE"

    def folders(self):
        return {"alle": ["INBOX", "Archive", "Deleted Messages", "Junk"]}

    def ensure_folder(self, name):
        self.angelegte_ordner.append(name)
        return True

    def search_window(self, folder, since=None, before=None, unseen_only=False):
        treffer = []
        for uid, m in sorted(self.nachrichten.items()):
            if m.folder != folder:
                continue
            if since and m.date.date() < since.date():
                continue
            if before and m.date.date() >= before.date():
                continue
            treffer.append(uid)
        return treffer

    def fetch_headers(self, folder, uids, progress=None):
        self.fetch_aufrufe += 1
        return [self.nachrichten[u] for u in uids]

    def neue_uid_nach_move(self, uid):
        """Echte Server vergeben beim Verschieben eine neue UID."""
        return uid + 10_000

    def move(self, folder, uids, target, progress=None):
        self.move_aufrufe += 1
        for u in uids:
            msg = self.nachrichten.pop(u)
            msg.folder = target
            # Neue UID vergeben - genau deshalb braucht das Rueckgaengig
            # die Message-ID und nicht die UID.
            msg.uid = self.neue_uid_nach_move(u)
            self.nachrichten[msg.uid] = msg
            self.bewegt.append((u, target))
        return len(uids)


def mach_nachrichten(n=60):
    msgs = []
    for i in range(n):
        alt = 200 if i % 2 else 2
        msgs.append(Message(
            message_id=f"<nachricht-{i}@example.com>",
            account="test", folder="INBOX", uid=i + 1,
            date=JETZT - timedelta(days=alt), size=10_000,
            flags=("\\Seen",) if i % 3 else (),
            from_addr=f"news{i % 5}@shop.de" if i % 2 else f"mensch{i}@partner.de",
            subject=f"Betreff {i}",
            to_addrs=("ich@example.com",),
            has_unsubscribe=bool(i % 2),
            list_id="<l>" if i % 2 else "",
        ))
    return msgs


class TestAblauf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self.tmp.name)
        (self.pfad / "konten.json").write_text(json.dumps({"konten": [{
            "name": "test", "host": "h", "benutzer": "u",
            "meine_adressen": ["ich@example.com"],
            "ordner": {"archiv": "Archive", "papierkorb": "Deleted Messages",
                       "spam": "Junk", "handeln": "Triage/1 Handeln",
                       "wartet": "Triage/2 Wartet", "lesen": "Triage/3 Lesen"},
        }], "einstellungen": {"max_aktionen_pro_lauf": 20}}), encoding="utf-8")
        (self.pfad / "regeln.json").write_text(json.dumps({
            "schutz": {}, "standard": {"kategorie": "unklar", "aktion": "pruefen"},
            "regeln": [
                {"name": "Alt-Bulk", "wenn": {"ist_massenversand": True,
                                              "aelter_als_tage": 45},
                 "dann": {"kategorie": "newsletter", "aktion": "loeschen"}},
                {"name": "Frisch direkt", "wenn": {"neuer_als_tage": 14,
                                                   "ist_massenversand": False},
                 "dann": {"kategorie": "geschaeftlich", "aktion": "handeln"}},
            ]}), encoding="utf-8")

        self.cfg = config.lade(self.pfad / "konten.json", self.pfad / "regeln.json")
        self.cfg.konten[0].passwort = lambda: "geheim"  # type: ignore[method-assign]
        self.postfach = FakePostfach("test", "h", 993, "u", "x").fuelle(mach_nachrichten())

        self._echt_planner = planner.Mailbox
        self._echt_applier = applier.Mailbox
        planner.Mailbox = lambda *a, **k: self.postfach
        applier.Mailbox = lambda *a, **k: self.postfach

    def tearDown(self):
        planner.Mailbox = self._echt_planner
        applier.Mailbox = self._echt_applier
        self.tmp.cleanup()

    def scanne(self, modus="taeglich", cursor=""):
        fortschritt = state.Fortschritt()
        if cursor:
            fortschritt.fuer("test").backlog_cursor = cursor
        lauf = planner.scanne(self.cfg.konten[0], self.cfg, modus, fortschritt,
                              jetzt=JETZT, leise=True)
        return planner.schreibe(lauf, self.cfg, ordner=self.pfad / "runs")

    # Die alten Nachrichten der Fixture liegen auf dem 01.03.2026.
    ALT_CURSOR = "2026-03-08"

    def test_scannen_erzeugt_plan_und_bericht(self):
        lauf = self.scanne()
        self.assertTrue(lauf.plan_pfad.exists())
        self.assertTrue(lauf.bericht_pfad.exists())
        self.assertGreater(len(lauf.eintraege), 0)

    def test_trockenlauf_bewegt_nichts(self):
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=False, leise=True)
        self.assertEqual(self.postfach.bewegt, [])
        self.assertEqual(self.postfach.move_aufrufe, 0)

    def test_anwenden_bewegt_und_haelt_das_limit_ein(self):
        lauf = self.scanne()
        ergebnis = applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        self.assertLessEqual(ergebnis.bewegt, 20)
        self.assertEqual(len(self.postfach.bewegt), ergebnis.bewegt)
        self.assertGreater(ergebnis.offen, 0)

    def test_zweiter_lauf_macht_weiter_statt_doppelt(self):
        lauf = self.scanne()
        erst = applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        bewegt_erst = list(self.postfach.bewegt)
        zweit = applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)

        uids_erst = {u for u, _ in bewegt_erst}
        uids_zweit = {u for u, _ in self.postfach.bewegt[len(bewegt_erst):]}
        self.assertFalse(uids_erst & uids_zweit, "Nachricht wurde doppelt bewegt")
        self.assertGreater(zweit.bewegt, 0)
        self.assertEqual(erst.bewegt + zweit.bewegt, len(self.postfach.bewegt))

    def test_passive_aktionen_werden_nie_bewegt(self):
        lauf = self.scanne()
        plan = json.loads(lauf.plan_pfad.read_text(encoding="utf-8"))
        passiv = {e["uid"] for e in plan["eintraege"] if e["aktion"] == "pruefen"}
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        self.assertFalse(passiv & {u for u, _ in self.postfach.bewegt})

    def test_geloeschtes_landet_im_papierkorb_nicht_im_nichts(self):
        lauf = self.scanne("backlog", cursor=self.ALT_CURSOR)
        self.assertTrue(any(e["aktion"] == "loeschen" for e in lauf.eintraege),
                        "Fixture liefert nichts zu Loeschendes")
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        ziele = {z for _, z in self.postfach.bewegt}
        self.assertTrue(ziele, "es wurde gar nichts bewegt")
        for ziel in ziele:
            self.assertIn(ziel, ["Deleted Messages", "Archive", "Junk",
                                 "Triage/1 Handeln", "Triage/2 Wartet",
                                 "Triage/3 Lesen"])

    def test_backlog_fenster_begrenzt_die_auswahl(self):
        lauf = self.scanne("backlog", cursor=self.ALT_CURSOR)
        self.assertGreater(len(lauf.eintraege), 0, "Fenster war leer")
        for e in lauf.eintraege:
            tag = datetime.fromisoformat(e["datum"]).date()
            self.assertGreaterEqual(tag, lauf.von)
            self.assertLess(tag, lauf.bis)

    def test_fehlende_zielordner_werden_angelegt(self):
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        self.assertTrue(any("Triage" in o for o in self.postfach.angelegte_ordner))


    def test_leeres_backlog_fenster_ist_kein_fehler(self):
        """Eine ruhige Woche im Backlog darf keinen Abbruch ausloesen."""
        lauf = self.scanne("backlog", cursor="2025-01-08")
        self.assertEqual(lauf.eintraege, [])
        ergebnis = applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        self.assertEqual(ergebnis.bewegt, 0)


class TestRueckgaengig(TestAblauf):
    """Ein ausgefuehrter Lauf muss sich zurueckdrehen lassen."""

    def test_alles_landet_wieder_im_posteingang(self):
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        bewegt = len(self.postfach.bewegt)
        self.assertGreater(bewegt, 0)
        nicht_inbox = [m for m in self.postfach.nachrichten.values()
                       if m.folder != "INBOX"]
        self.assertEqual(len(nicht_inbox), bewegt)

        ergebnis = applier.mache_rueckgaengig(lauf.plan_pfad, self.cfg,
                                              ja=True, leise=True)
        self.assertEqual(ergebnis.bewegt, bewegt)
        self.assertEqual(ergebnis.nicht_gefunden, 0)
        self.assertEqual(
            [m for m in self.postfach.nachrichten.values() if m.folder != "INBOX"], [])

    def test_trockenlauf_holt_nichts_zurueck(self):
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        vorher = len(self.postfach.bewegt)
        applier.mache_rueckgaengig(lauf.plan_pfad, self.cfg, ja=False, leise=True)
        self.assertEqual(len(self.postfach.bewegt), vorher)

    def test_plan_gilt_danach_wieder_als_offen(self):
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        applier.mache_rueckgaengig(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        plan = json.loads(lauf.plan_pfad.read_text(encoding="utf-8"))
        self.assertFalse(any(e.get("erledigt") for e in plan["eintraege"]))
        self.assertTrue(any(e.get("rueckgaengig") for e in plan["eintraege"]))

    def test_ohne_message_id_wird_ehrlich_gemeldet(self):
        for m in self.postfach.nachrichten.values():
            m.message_id = ""
        lauf = self.scanne()
        applier.wende_an(lauf.plan_pfad, self.cfg, ja=True, leise=True)
        ergebnis = applier.mache_rueckgaengig(lauf.plan_pfad, self.cfg,
                                              ja=True, leise=True)
        self.assertEqual(ergebnis.bewegt, 0)
        self.assertGreater(ergebnis.nicht_gefunden, 0)

    def test_nichts_ausgefuehrt_nichts_zurueckzudrehen(self):
        lauf = self.scanne()
        ergebnis = applier.mache_rueckgaengig(lauf.plan_pfad, self.cfg,
                                              ja=True, leise=True)
        self.assertEqual(ergebnis.bewegt, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
