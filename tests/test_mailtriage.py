"""Tests fuer die Teile, in denen echte Mails verlorengehen koennten."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mailtriage import imap_utf7, report, state  # noqa: E402
from mailtriage.config import Konto  # noqa: E402
from mailtriage.mailbox import imap_date, parse_internaldate  # noqa: E402
from mailtriage.model import Message, parse_headers  # noqa: E402
from mailtriage.rules import klassifiziere, passt, pruefe_regelwerk  # noqa: E402
from mailtriage.taxonomy import AKTIONEN, KATEGORIEN  # noqa: E402

JETZT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
KONTO = Konto(name="test", host="h", benutzer="u",
              meine_adressen=("ich@example.com",))


def mach_msg(**kw) -> Message:
    basis = dict(account="test", folder="INBOX", uid=1,
                 date=JETZT - timedelta(days=1), size=1000)
    basis.update(kw)
    return Message(**basis)


class TestImapUtf7(unittest.TestCase):
    def test_hin_und_zurueck(self):
        for name in ["INBOX", "Archiv", "Archiv/Immobilien", "Gelöschte Objekte",
                     "Entwürfe", "R&D", "Späße & Ähnliches", "Junk-E-Mail"]:
            self.assertEqual(imap_utf7.decode(imap_utf7.encode(name)), name)

    def test_ascii_bleibt_unveraendert(self):
        self.assertEqual(imap_utf7.encode("Triage/1 Handeln"), b"Triage/1 Handeln")

    def test_kaputte_kodierung_stuerzt_nicht_ab(self):
        self.assertIsInstance(imap_utf7.decode(b"&nichtbase64"), str)


class TestDatumsParsen(unittest.TestCase):
    def test_internaldate_mit_zeitzone(self):
        self.assertEqual(parse_internaldate(b"17-Sep-2026 12:34:56 +0200"),
                         datetime(2026, 9, 17, 10, 34, 56, tzinfo=timezone.utc))

    def test_internaldate_negativer_offset(self):
        self.assertEqual(parse_internaldate(b"01-Jan-2019 00:05:00 -0500"),
                         datetime(2019, 1, 1, 5, 5, tzinfo=timezone.utc))

    def test_imap_date_format(self):
        self.assertEqual(imap_date(datetime(2026, 9, 3, tzinfo=timezone.utc)), "03-Sep-2026")


class TestKopfzeilen(unittest.TestCase):
    def test_mime_dekodierung_und_normalisierung(self):
        roh = (b"From: =?utf-8?B?SsO8cmdlbiBTY2jDpGZlcg==?= <Juergen@Example.COM>\r\n"
               b"To: ich@example.com, kollege@example.com\r\n"
               b"Subject: =?utf-8?Q?Angebot_f=C3=BCr_die_Immobilie?=\r\n"
               b"List-Unsubscribe: <https://x/u>\r\n\r\n")
        m = parse_headers("test", "INBOX", 7, JETZT, 1234, ("\\Seen",), roh)
        self.assertEqual(m.from_name, "Jürgen Schäfer")
        self.assertEqual(m.from_addr, "juergen@example.com")
        self.assertEqual(m.from_domain, "example.com")
        self.assertEqual(m.subject, "Angebot für die Immobilie")
        self.assertIn("ich@example.com", m.to_addrs)
        self.assertTrue(m.is_bulk)
        self.assertTrue(m.seen)

    def test_kaputte_kopfzeilen(self):
        m = parse_headers("test", "INBOX", 1, JETZT, 0, (), b"Subject: \xff\xfe kaputt\r\n\r\n")
        self.assertIsInstance(m.subject, str)

    def test_flags(self):
        m = mach_msg(flags=("\\Seen", "\\Answered", "\\Flagged"))
        self.assertTrue(m.seen and m.answered and m.flagged)
        self.assertFalse(mach_msg(flags=()).seen)


class TestBedingungen(unittest.TestCase):
    def test_domain_trifft_auch_subdomain(self):
        m = mach_msg(from_addr="x@mail.example.com")
        self.assertTrue(passt({"von_domain": ["example.com"]}, m, KONTO, JETZT))
        self.assertFalse(passt({"von_domain": ["beispiel.com"]}, m, KONTO, JETZT))

    def test_domain_trifft_nicht_bei_aehnlichem_suffix(self):
        m = mach_msg(from_addr="x@nichtexample.com")
        self.assertFalse(passt({"von_domain": ["example.com"]}, m, KONTO, JETZT))

    def test_alle_bedingungen_muessen_passen(self):
        m = mach_msg(has_unsubscribe=True, date=JETZT - timedelta(days=10))
        self.assertTrue(passt({"ist_massenversand": True}, m, KONTO, JETZT))
        self.assertFalse(
            passt({"ist_massenversand": True, "aelter_als_tage": 45}, m, KONTO, JETZT))

    def test_an_mich_direkt(self):
        direkt = mach_msg(to_addrs=("ich@example.com",))
        kopie = mach_msg(to_addrs=("liste@example.com",))
        self.assertTrue(passt({"an_mich_direkt": True}, direkt, KONTO, JETZT))
        self.assertFalse(passt({"an_mich_direkt": True}, kopie, KONTO, JETZT))

    def test_unbekannte_bedingung_faellt_auf(self):
        with self.assertRaises(ValueError):
            passt({"gibt_es_nicht": 1}, mach_msg(), KONTO, JETZT)

    def test_betreff_ist_case_insensitive(self):
        m = mach_msg(subject="Dringende MAHNUNG")
        self.assertTrue(passt({"betreff_enthaelt": ["mahnung"]}, m, KONTO, JETZT))


class TestKlassifikation(unittest.TestCase):
    REGELN = [
        {"name": "Alt-Newsletter",
         "wenn": {"ist_massenversand": True, "aelter_als_tage": 45},
         "dann": {"kategorie": "newsletter", "aktion": "loeschen"}},
        {"name": "Immobilien",
         "wenn": {"betreff_enthaelt": ["Nebenkosten"]},
         "dann": {"kategorie": "immobilien", "aktion": "archivieren",
                  "unterordner": "Immobilien"}},
    ]
    STANDARD = {"kategorie": "unklar", "aktion": "pruefen"}
    SCHUTZ = {"von_domain": ["steuerberater.de"], "kommentar": "Steuerberater"}

    def klass(self, msg):
        return klassifiziere(msg, self.REGELN, self.STANDARD, self.SCHUTZ, KONTO, JETZT)

    def test_erste_passende_regel_gewinnt(self):
        m = mach_msg(has_unsubscribe=True, subject="Nebenkosten",
                     date=JETZT - timedelta(days=100))
        self.assertEqual(self.klass(m).regel, "Alt-Newsletter")

    def test_ohne_treffer_wird_nichts_angefasst(self):
        e = self.klass(mach_msg(subject="Hallo"))
        self.assertEqual(e.aktion, "pruefen")
        self.assertIsNone(e.zielordner)
        self.assertFalse(e.bewegt)

    def test_markierte_mail_wird_nie_geloescht(self):
        m = mach_msg(has_unsubscribe=True, date=JETZT - timedelta(days=100),
                     flags=("\\Flagged",))
        e = self.klass(m)
        self.assertEqual(e.aktion, "pruefen")
        self.assertIn("markiert", e.schutz)

    def test_schutzliste_verhindert_loeschen(self):
        m = mach_msg(has_unsubscribe=True, from_addr="kanzlei@steuerberater.de",
                     date=JETZT - timedelta(days=100))
        e = self.klass(m)
        self.assertEqual(e.aktion, "pruefen")
        self.assertEqual(e.schutz, "Steuerberater")

    def test_schutz_blockiert_nur_destruktives(self):
        m = mach_msg(subject="Nebenkosten", from_addr="kanzlei@steuerberater.de")
        e = self.klass(m)
        self.assertEqual(e.aktion, "archivieren")
        self.assertEqual(e.schutz, "")

    def test_unterordner_im_archiv(self):
        e = self.klass(mach_msg(subject="Nebenkosten"))
        self.assertTrue(e.zielordner.endswith("/Immobilien"))

    def test_beispielregelwerk_ist_gueltig(self):
        roh = json.loads(
            (Path(__file__).parent.parent / "config" / "regeln.beispiel.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(
            pruefe_regelwerk(roh["regeln"], roh["standard"], KONTO), [])

    def test_beispielregelwerk_loescht_nichts_frisches(self):
        """Eine Mail von heute darf keine Regel in den Papierkorb schicken."""
        roh = json.loads(
            (Path(__file__).parent.parent / "config" / "regeln.beispiel.json")
            .read_text(encoding="utf-8"))
        for bulk in (True, False):
            for direkt in (True, False):
                m = mach_msg(date=JETZT - timedelta(hours=2), has_unsubscribe=bulk,
                             subject="Irgendwas", from_addr="wer@fremd.de",
                             to_addrs=("ich@example.com",) if direkt else ("x@y.de",))
                e = klassifiziere(m, roh["regeln"], roh["standard"],
                                  roh["schutz"], KONTO, JETZT)
                self.assertNotEqual(e.aktion, "loeschen",
                                    f"frische Mail geloescht (bulk={bulk}, direkt={direkt})")


class TestTaxonomie(unittest.TestCase):
    def test_jede_aktion_hat_eine_gueltige_ordnerrolle(self):
        from mailtriage.config import STANDARD_ORDNER
        for aktion, (_, rolle) in AKTIONEN.items():
            if rolle is not None:
                self.assertIn(rolle, STANDARD_ORDNER, f"Aktion {aktion}")

    def test_reihenfolgen_sind_vollstaendig(self):
        from mailtriage.taxonomy import AKTION_REIHENFOLGE, KATEGORIE_REIHENFOLGE
        self.assertEqual(set(AKTION_REIHENFOLGE), set(AKTIONEN))
        self.assertEqual(set(KATEGORIE_REIHENFOLGE), set(KATEGORIEN))


class TestBacklogFenster(unittest.TestCase):
    def test_arbeitet_wochenweise_rueckwaerts(self):
        s = state.KontoStatus(backlog_cursor="2026-09-10")
        fenster = []
        for _ in range(3):
            von, bis = state.backlog_fenster(s, 7, 7)
            fenster.append((von, bis))
            state.nach_backlog_lauf(s, von, anzahl=10)
        self.assertEqual(fenster, [
            (date(2026, 9, 3), date(2026, 9, 10)),
            (date(2026, 8, 27), date(2026, 9, 3)),
            (date(2026, 8, 20), date(2026, 8, 27)),
        ])
        self.assertEqual(s.wochen_erledigt, 3)

    def test_fenster_sind_luecklos_und_ueberschneidungsfrei(self):
        s = state.KontoStatus(backlog_cursor="2026-09-10")
        letztes_von = None
        for _ in range(10):
            von, bis = state.backlog_fenster(s, 7, 7)
            if letztes_von is not None:
                self.assertEqual(bis, letztes_von)
            letztes_von = von
            state.nach_backlog_lauf(s, von, anzahl=1)

    def test_endet_bei_der_aeltesten_mail(self):
        s = state.KontoStatus(backlog_cursor="2026-09-10", aeltester_fund="2026-09-01")
        for _ in range(3):
            von, _ = state.backlog_fenster(s, 7, 7)
            state.nach_backlog_lauf(s, von, anzahl=0)
        self.assertTrue(s.backlog_fertig)

    def test_leere_wochen_beenden_nicht_sofort(self):
        s = state.KontoStatus(backlog_cursor="2026-09-10")
        von, _ = state.backlog_fenster(s, 7, 7)
        state.nach_backlog_lauf(s, von, anzahl=0)
        self.assertFalse(s.backlog_fertig)

    def test_taegliches_fenster_ueberlappt_einen_tag(self):
        s = state.KontoStatus(letzter_taeglicher_lauf="2026-09-17T10:00:00+00:00")
        self.assertEqual(state.taegliches_fenster(s), date(2026, 9, 16))

    def test_status_ueberlebt_speichern_und_laden(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "f.json"
            f = state.Fortschritt()
            f.fuer("icloud").backlog_cursor = "2026-05-01"
            f.fuer("icloud").wochen_erledigt = 12
            state.speichere(f, pfad)
            self.assertEqual(state.lade(pfad).fuer("icloud").wochen_erledigt, 12)


class TestBericht(unittest.TestCase):
    def eintraege(self, n: int) -> list[dict]:
        return [{
            "aktion": ["loeschen", "archivieren", "handeln", "pruefen"][i % 4],
            "kategorie": ["newsletter", "immobilien", "investment", "unklar"][i % 4],
            "absender": f"Absender {i % 50}", "absender_adresse": f"a{i % 50}@d{i % 9}.de",
            "betreff": f"Betreff {i} " + "x" * 90,
            "datum": "2026-08-01T10:00:00+00:00", "groesse": 50_000,
            "regel": "R", "schutz": "",
        } for i in range(n)]

    def test_bericht_bleibt_klein_bei_vielen_mails(self):
        for n in (10, 1_000, 50_000):
            zeilen = len(report.baue_bericht(
                self.eintraege(n), konto="k", modus="backlog",
                fenster=None, max_zeilen=220).splitlines())
            self.assertLessEqual(zeilen, 220, f"{n} Mails ergaben {zeilen} Zeilen")

    def test_summen_stimmen(self):
        text = report.baue_bericht(self.eintraege(400), konto="k",
                                   modus="test", fenster=None)
        self.assertIn("400", text)
        self.assertIn("loeschen", text)

    def test_kurzfassung_ist_eine_zeile(self):
        kurz = report.kurzfassung(self.eintraege(1000), "icloud")
        self.assertEqual(len(kurz.splitlines()), 1)
        self.assertIn("1000", kurz)

    def test_leerer_lauf(self):
        self.assertIn("Triage-Vorschlag",
                      report.baue_bericht([], konto="k", modus="test", fenster=None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
