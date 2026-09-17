"""Ein minimaler IMAP-Server fuer die Tests.

Die uebrigen Tests ersetzen die Mailbox-Klasse durch eine Attrappe. Das prueft
die Logik, aber nicht das, was am Draht passiert: Literale, UTF-7-Ordnernamen,
die Reihenfolge der FETCH-Antwort. Genau dort sitzen die Fehler, die man erst
auf dem echten Postfach merkt.

Dieser Server spricht echtes IMAP ueber einen echten TLS-Socket, damit der
Produktionscode unveraendert dagegen laufen kann.
"""

from __future__ import annotations

import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mailtriage import imap_utf7  # noqa: E402


def selbstsigniertes_zertifikat(ordner: Path) -> tuple[Path, Path]:
    """Erzeugt Zertifikat und Schluessel fuer localhost."""
    cert, key = ordner / "cert.pem", ordner / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "2",
         "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    return cert, key


class Nachricht:
    def __init__(self, uid: int, internaldate: str, flags: str, kopf: bytes):
        self.uid = uid
        self.internaldate = internaldate
        self.flags = flags
        self.kopf = kopf


class IMAPTestServer(threading.Thread):
    """Spricht so viel IMAP, wie mailtriage benutzt.

    flags_nach_literal schaltet die Reihenfolge der FETCH-Antwort um: manche
    Server liefern FLAGS vor dem BODY-Literal, andere danach. Beides muss der
    Client verkraften.
    """

    FAEHIGKEITEN = "IMAP4rev1 MOVE UNSELECT UIDPLUS AUTH=PLAIN"

    def __init__(self, cert: Path, key: Path, *, flags_nach_literal: bool = False,
                 kann_move: bool = True, kann_unselect: bool = True):
        super().__init__(daemon=True)
        self.flags_nach_literal = flags_nach_literal
        self.kann_move = kann_move
        self.kann_unselect = kann_unselect

        self.ordner: dict[str, list[Nachricht]] = {
            "INBOX": [], "Archive": [], "Deleted Messages": [], "Junk": [],
        }
        self.protokoll: list[str] = []
        self.angelegt: list[str] = []
        self._offen: str | None = None
        self._readonly = True

        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(str(cert), str(key))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._laeuft = True

    # -- Testhilfen ----------------------------------------------------

    def fuelle(self, ordner: str, nachrichten: list[Nachricht]) -> None:
        self.ordner.setdefault(ordner, []).extend(nachrichten)

    def faehigkeiten(self) -> str:
        teile = ["IMAP4rev1", "UIDPLUS", "AUTH=PLAIN"]
        if self.kann_move:
            teile.append("MOVE")
        if self.kann_unselect:
            teile.append("UNSELECT")
        return " ".join(teile)

    def stop(self) -> None:
        self._laeuft = False
        try:
            self._sock.close()
        except OSError:
            pass

    # -- Server --------------------------------------------------------

    def run(self) -> None:
        while self._laeuft:
            try:
                roh, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._bediene, args=(roh,), daemon=True).start()

    def _bediene(self, roh: socket.socket) -> None:
        try:
            conn = self._ctx.wrap_socket(roh, server_side=True)
        except (ssl.SSLError, OSError):
            return
        datei = conn.makefile("rwb")
        self._sende(datei, f"* OK [CAPABILITY {self.faehigkeiten()}] Testserver bereit")

        try:
            while self._laeuft:
                zeile = datei.readline()
                if not zeile:
                    return
                if self._verarbeite(datei, zeile.decode("utf-8", "replace").strip()):
                    return
        except (OSError, ssl.SSLError, ValueError):
            return
        finally:
            try:
                datei.close()
                conn.close()
            except OSError:
                pass

    def _sende(self, datei, text: str) -> None:
        datei.write(text.encode("utf-8") + b"\r\n")
        datei.flush()

    def _sende_roh(self, datei, daten: bytes) -> None:
        datei.write(daten)
        datei.flush()

    # -- Kommandos -----------------------------------------------------

    def _verarbeite(self, datei, zeile: str) -> bool:
        teile = zeile.split(" ", 2)
        tag = teile[0]
        befehl = teile[1].upper() if len(teile) > 1 else ""
        rest = teile[2] if len(teile) > 2 else ""

        if befehl == "UID":
            unter = rest.split(" ", 1)
            befehl = "UID " + unter[0].upper()
            rest = unter[1] if len(unter) > 1 else ""

        self.protokoll.append(befehl)

        if befehl == "CAPABILITY":
            self._sende(datei, f"* CAPABILITY {self.faehigkeiten()}")
            self._sende(datei, f"{tag} OK CAPABILITY abgeschlossen")
        elif befehl == "LOGIN":
            if "falsch" in rest:
                self._sende(datei, f"{tag} NO Anmeldung fehlgeschlagen")
            else:
                self._sende(datei, f"{tag} OK angemeldet")
        elif befehl == "LIST":
            for name in self.ordner:
                sonder = {"Archive": r" \Archive", "Deleted Messages": r" \Trash",
                          "Junk": r" \Junk"}.get(name, "")
                kodiert = imap_utf7.encode(name).decode("ascii")
                self._sende(datei, f'* LIST (\\HasNoChildren{sonder}) "/" "{kodiert}"')
            self._sende(datei, f"{tag} OK LIST abgeschlossen")
        elif befehl == "CREATE":
            name = self._ordnername(rest)
            self.angelegt.append(name)
            self.ordner.setdefault(name, [])
            self._sende(datei, f"{tag} OK CREATE abgeschlossen")
        elif befehl == "SUBSCRIBE":
            self._sende(datei, f"{tag} OK SUBSCRIBE abgeschlossen")
        elif befehl in ("SELECT", "EXAMINE"):
            name = self._ordnername(rest)
            if name not in self.ordner:
                self._sende(datei, f"{tag} NO Ordner nicht vorhanden")
                return False
            self._offen = name
            self._readonly = befehl == "EXAMINE"
            self._sende(datei, f"* {len(self.ordner[name])} EXISTS")
            self._sende(datei, "* 0 RECENT")
            self._sende(datei, "* OK [UIDVALIDITY 1] UIDs gueltig")
            zustand = "READ-ONLY" if self._readonly else "READ-WRITE"
            self._sende(datei, f"{tag} OK [{zustand}] abgeschlossen")
        elif befehl == "CLOSE":
            self._offen = None
            self._sende(datei, f"{tag} OK CLOSE abgeschlossen")
        elif befehl == "UNSELECT":
            if not self.kann_unselect:
                self._sende(datei, f"{tag} BAD UNSELECT unbekannt")
                return False
            self._offen = None
            self._sende(datei, f"{tag} OK UNSELECT abgeschlossen")
        elif befehl == "UID SEARCH":
            self._suche(datei, tag, rest)
        elif befehl == "UID FETCH":
            self._hole(datei, tag, rest)
        elif befehl == "UID MOVE":
            self._verschiebe(datei, tag, rest)
        elif befehl == "UID COPY":
            self._verschiebe(datei, tag, rest, kopieren=True)
        elif befehl == "UID STORE":
            self._sende(datei, f"{tag} OK STORE abgeschlossen")
        elif befehl == "UID EXPUNGE":
            self._sende(datei, f"{tag} OK EXPUNGE abgeschlossen")
        elif befehl == "LOGOUT":
            self._sende(datei, "* BYE tschuess")
            self._sende(datei, f"{tag} OK LOGOUT abgeschlossen")
            return True
        elif befehl == "NOOP":
            self._sende(datei, f"{tag} OK NOOP abgeschlossen")
        else:
            self._sende(datei, f"{tag} BAD unbekanntes Kommando {befehl}")
        return False

    def _ordnername(self, roh: str) -> str:
        """Ordnernamen kommen IMAP-UTF-7-kodiert an."""
        return imap_utf7.decode(roh.strip().strip('"').encode("ascii", "replace"))

    def _aktuelle(self) -> list[Nachricht]:
        return self.ordner.get(self._offen or "", [])

    def _suche(self, datei, tag: str, kriterien: str) -> None:
        treffer = [n for n in self._aktuelle()]

        seit = re.search(r"SINCE (\S+)", kriterien, re.IGNORECASE)
        vor = re.search(r"BEFORE (\S+)", kriterien, re.IGNORECASE)

        def als_datum(text: str) -> datetime:
            return datetime.strptime(text.strip('"'), "%d-%b-%Y")

        def datum_von(n: Nachricht) -> datetime:
            return datetime.strptime(n.internaldate.split(" ")[0], "%d-%b-%Y")

        if seit:
            treffer = [n for n in treffer if datum_von(n) >= als_datum(seit.group(1))]
        if vor:
            treffer = [n for n in treffer if datum_von(n) < als_datum(vor.group(1))]
        if re.search(r"\bUNSEEN\b", kriterien, re.IGNORECASE):
            treffer = [n for n in treffer if "\\Seen" not in n.flags]

        self._sende(datei, "* SEARCH " + " ".join(str(n.uid) for n in treffer))
        self._sende(datei, f"{tag} OK SEARCH abgeschlossen")

    def _hole(self, datei, tag: str, rest: str) -> None:
        menge, _, _ = rest.partition(" ")
        gesucht = {int(u) for u in menge.split(",") if u.strip().isdigit()}
        for nummer, n in enumerate(self._aktuelle(), start=1):
            if n.uid not in gesucht:
                continue
            vorne = (f"UID {n.uid} INTERNALDATE \"{n.internaldate}\" "
                     f"RFC822.SIZE {len(n.kopf)}")
            if not self.flags_nach_literal:
                vorne += f" FLAGS ({n.flags})"
            hinten = f" FLAGS ({n.flags}))" if self.flags_nach_literal else ")"

            self._sende_roh(datei, (
                f"* {nummer} FETCH ({vorne} "
                f"BODY[HEADER.FIELDS (FROM TO SUBJECT)] {{{len(n.kopf)}}}\r\n"
            ).encode("utf-8"))
            self._sende_roh(datei, n.kopf)
            self._sende_roh(datei, hinten.encode("utf-8") + b"\r\n")
        self._sende(datei, f"{tag} OK FETCH abgeschlossen")

    def _verschiebe(self, datei, tag: str, rest: str, kopieren: bool = False) -> None:
        if not kopieren and not self.kann_move:
            self._sende(datei, f"{tag} BAD MOVE unbekannt")
            return
        menge, _, ziel_roh = rest.partition(" ")
        ziel = self._ordnername(ziel_roh)
        gesucht = {int(u) for u in menge.split(",") if u.strip().isdigit()}
        quelle = self._aktuelle()
        bewegt = [n for n in quelle if n.uid in gesucht]
        for n in bewegt:
            quelle.remove(n)
            n.uid += 10_000          # Server vergeben beim Verschieben neue UIDs
            self.ordner.setdefault(ziel, []).append(n)
        wort = "COPY" if kopieren else "MOVE"
        self._sende(datei, f"{tag} OK [COPYUID 1 x y] {wort} abgeschlossen")


def starte_server(**kw) -> tuple[IMAPTestServer, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    cert, key = selbstsigniertes_zertifikat(Path(tmp.name))
    server = IMAPTestServer(cert, key, **kw)
    server.start()
    return server, tmp, cert
