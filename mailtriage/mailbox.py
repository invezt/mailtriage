"""IMAP-Zugriff - bewusst sparsam, damit nichts abstuerzt.

Drei Regeln, die hier durchgehalten werden:

1. Es werden nur Kopfzeilen geladen (BODY.PEEK[HEADER.FIELDS ...]).
   Nie ein Nachrichtenrumpf, nie ein Anhang.
2. Alles laeuft in Bloecken mit Pause dazwischen. Kein einziges Kommando
   fasst mehr als CHUNK_MOVE Nachrichten an.
3. Nichts wird endgueltig geloescht. "Loeschen" heisst: ab in den
   Papierkorb. Von dort ist alles wiederherstellbar.

Damit laeuft die Arbeit serverseitig. Apple Mail synchronisiert danach nur
noch das Ergebnis - statt ueber AppleScript zehntausende Apple Events zu
verarbeiten, woran es bisher zerbrochen ist.
"""

from __future__ import annotations

import imaplib
import re
import ssl
import time
from datetime import datetime, timedelta, timezone

from . import imap_utf7
from .model import HEADER_FIELDS, Message, parse_headers

# Wie viele Nachrichten ein einzelnes Kommando anfasst.
CHUNK_FETCH = 200
CHUNK_MOVE = 100
# Pause zwischen Bloecken, damit der Server (und der Mac) Luft bekommt.
PAUSE_SECONDS = 0.2

imaplib._MAXLINE = max(imaplib._MAXLINE, 10_000_000)

_UID_RE = re.compile(rb"\bUID\s+(\d+)")
_SIZE_RE = re.compile(rb"\bRFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"\bFLAGS\s+\(([^)]*)\)")
_DATE_RE = re.compile(rb'\bINTERNALDATE\s+"([^"]+)"')
_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}

# Special-Use-Kennzeichnungen (RFC 6154) -> unsere Rollennamen.
SPECIAL_USE = {
    "\\archive": "archiv",
    "\\junk": "spam",
    "\\trash": "papierkorb",
    "\\sent": "gesendet",
    "\\drafts": "entwuerfe",
}


class MailboxError(RuntimeError):
    pass


def parse_internaldate(raw: bytes) -> datetime:
    """'17-Sep-2026 12:34:56 +0200' -> aware datetime (UTC)."""
    text = raw.decode("ascii", "replace").strip()
    try:
        day, month, rest = text.split("-", 2)
        year, clock, offset = rest.split(" ", 2)
        hour, minute, second = (int(p) for p in clock.split(":"))
        sign = -1 if offset.startswith("-") else 1
        tz = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
        return datetime(int(year), _MONTHS[month], int(day),
                        hour, minute, second, tzinfo=tz).astimezone(timezone.utc)
    except (ValueError, KeyError) as exc:
        raise MailboxError(f"INTERNALDATE unlesbar: {text!r}") from exc


def imap_date(value: datetime) -> str:
    """datetime -> '17-Sep-2026', wie IMAP es fuer SINCE/BEFORE erwartet."""
    month = [k for k, v in _MONTHS.items() if v == value.month][0]
    return f"{value.day:02d}-{month}-{value.year}"


def _quote(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class Mailbox:
    """Ein Postfach. Als Context-Manager benutzen."""

    def __init__(self, account: str, host: str, port: int, user: str,
                 password: str, timeout: int = 60, verbose: bool = False):
        self.account = account
        self.host = host
        self.port = port
        self.user = user
        self._password = password
        self.timeout = timeout
        self.verbose = verbose
        self._imap: imaplib.IMAP4_SSL | None = None
        self._capabilities: frozenset[str] = frozenset()
        self._selected: str | None = None
        self._selected_readonly = True
        self._anzahl = 0

    # -- Verbindung ----------------------------------------------------

    def __enter__(self) -> "Mailbox":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def connect(self, retries: int = 3) -> None:
        last: Exception | None = None
        for attempt in range(retries):
            try:
                self._imap = imaplib.IMAP4_SSL(
                    self.host, self.port,
                    ssl_context=ssl.create_default_context(),
                    timeout=self.timeout,
                )
                self._imap.login(self.user, self._password)
                self._capabilities = frozenset(
                    c.decode().upper() for c in (self._imap.capabilities or ()))
                self._log(f"verbunden mit {self.host} als {self.user}")
                return
            except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
                last = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise MailboxError(
            f"Konto {self.account}: Login bei {self.host} fehlgeschlagen ({last}). "
            "Bei iCloud braucht es ein app-spezifisches Passwort, nicht das Apple-ID-Passwort."
        ) from last

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            if self._selected:
                self._imap.close()
            self._imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        finally:
            self._imap = None
            self._selected = None

    @property
    def imap(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            raise MailboxError("Nicht verbunden - erst connect() aufrufen.")
        return self._imap

    def has(self, capability: str) -> bool:
        return capability.upper() in self._capabilities

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"  [{self.account}] {message}")

    def _ok(self, typ: str, data, what: str):
        if typ != "OK":
            detail = data[0].decode(errors="replace") if data and data[0] else ""
            raise MailboxError(f"Konto {self.account}: {what} fehlgeschlagen ({typ}) {detail}")
        return data

    # -- Ordner --------------------------------------------------------

    def folders(self) -> dict[str, list[str]]:
        """Alle Ordner. Gibt {'alle': [...], 'archiv': [...], ...} zurueck."""
        typ, data = self.imap.list()
        self._ok(typ, data, "LIST")
        result: dict[str, list[str]] = {"alle": []}
        for line in data:
            if not line:
                continue
            if isinstance(line, tuple):
                line = b" ".join(line)
            match = re.match(rb'\((?P<flags>[^)]*)\)\s+"?(?P<sep>[^"\s]*)"?\s+(?P<name>.+)$', line)
            if not match:
                continue
            name = match.group("name").strip()
            if name.startswith(b'"') and name.endswith(b'"'):
                name = name[1:-1]
            decoded = imap_utf7.decode(name)
            result["alle"].append(decoded)
            for flag in match.group("flags").decode(errors="replace").lower().split():
                role = SPECIAL_USE.get(flag)
                if role:
                    result.setdefault(role, []).append(decoded)
        return result

    def ensure_folder(self, name: str) -> bool:
        """Legt einen Ordner an, falls er fehlt. True = neu erstellt."""
        if name in self.folders()["alle"]:
            return False
        typ, data = self.imap.create(_quote(imap_utf7.encode(name).decode("ascii")))
        if typ != "OK":
            detail = data[0].decode(errors="replace") if data and data[0] else ""
            if b"exist" in detail.lower().encode():
                return False
            raise MailboxError(f"Konto {self.account}: Ordner {name!r} anlegen fehlgeschlagen: {detail}")
        try:
            self.imap.subscribe(_quote(imap_utf7.encode(name).decode("ascii")))
        except imaplib.IMAP4.error:
            pass
        self._log(f"Ordner angelegt: {name}")
        return True

    def select(self, folder: str, readonly: bool = True) -> int:
        """Ordner oeffnen. Gibt die Anzahl Nachrichten zurueck.

        Ist der Ordner bereits im passenden Modus offen, passiert nichts -
        move() ruft das pro Zielordner auf, und ein erneutes SELECT auf ein
        Postfach mit zehntausenden Nachrichten waere reine Verschwendung.
        """
        if self._selected == folder and self._selected_readonly == readonly:
            return self._anzahl
        if self._selected:
            try:
                self.imap.close()
            except imaplib.IMAP4.error:
                pass
        encoded = _quote(imap_utf7.encode(folder).decode("ascii"))
        typ, data = self.imap.select(encoded, readonly=readonly)
        self._ok(typ, data, f"SELECT {folder!r}")
        self._selected = folder
        self._selected_readonly = readonly
        self._anzahl = int(data[0]) if data and data[0] else 0
        return self._anzahl

    # -- Lesen ---------------------------------------------------------

    def search_window(self, folder: str, since: datetime | None = None,
                      before: datetime | None = None,
                      unseen_only: bool = False) -> list[int]:
        """UIDs im Zeitfenster [since, before). Serverseitig, ohne Download."""
        self.select(folder, readonly=True)
        criteria: list[str] = []
        if since is not None:
            criteria += ["SINCE", imap_date(since)]
        if before is not None:
            criteria += ["BEFORE", imap_date(before)]
        if unseen_only:
            criteria.append("UNSEEN")
        if not criteria:
            criteria = ["ALL"]
        typ, data = self.imap.uid("SEARCH", None, *criteria)
        self._ok(typ, data, f"SEARCH {criteria}")
        uids = [int(u) for u in (data[0] or b"").split()]
        self._log(f"{folder}: {len(uids)} Nachrichten im Fenster")
        return uids

    def fetch_headers(self, folder: str, uids: list[int],
                      progress=None) -> list[Message]:
        """Kopfzeilen in Bloecken holen. Der Rumpf bleibt auf dem Server."""
        if not uids:
            return []
        self.select(folder, readonly=True)
        fields = " ".join(HEADER_FIELDS)
        spec = f"(UID INTERNALDATE RFC822.SIZE FLAGS BODY.PEEK[HEADER.FIELDS ({fields})])"
        messages: list[Message] = []

        for start in range(0, len(uids), CHUNK_FETCH):
            block = uids[start:start + CHUNK_FETCH]
            typ, data = self.imap.uid("FETCH", ",".join(str(u) for u in block), spec)
            self._ok(typ, data, "FETCH")
            for item in data:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                prefix, raw_headers = item[0], item[1]
                uid_match = _UID_RE.search(prefix)
                date_match = _DATE_RE.search(prefix)
                if not uid_match or not date_match:
                    continue
                size_match = _SIZE_RE.search(prefix)
                flags_match = _FLAGS_RE.search(prefix)
                flags = tuple(
                    flags_match.group(1).decode(errors="replace").split()
                ) if flags_match else ()
                messages.append(parse_headers(
                    account=self.account,
                    folder=folder,
                    uid=int(uid_match.group(1)),
                    internaldate=parse_internaldate(date_match.group(1)),
                    size=int(size_match.group(1)) if size_match else 0,
                    flags=flags,
                    raw_headers=raw_headers or b"",
                ))
            if progress:
                progress(min(start + CHUNK_FETCH, len(uids)), len(uids))
            time.sleep(PAUSE_SECONDS)

        self._log(f"{folder}: {len(messages)} Kopfzeilen gelesen")
        return messages

    # -- Schreiben -----------------------------------------------------

    def move(self, folder: str, uids: list[int], target: str,
             progress=None) -> int:
        """Verschiebt Nachrichten in Bloecken. Gibt die Anzahl zurueck.

        Kein endgueltiges Loeschen: "Loeschen" bedeutet Verschieben in den
        Papierkorb, und der Papierkorb wird hier nie geleert.
        """
        if not uids:
            return 0
        if folder == target:
            return 0
        self.select(folder, readonly=False)
        encoded = _quote(imap_utf7.encode(target).decode("ascii"))
        moved = 0

        for start in range(0, len(uids), CHUNK_MOVE):
            block = uids[start:start + CHUNK_MOVE]
            uid_set = ",".join(str(u) for u in block)

            if self.has("MOVE"):
                typ, data = self.imap.uid("MOVE", uid_set, encoded)
                self._ok(typ, data, f"MOVE -> {target!r}")
            else:
                typ, data = self.imap.uid("COPY", uid_set, encoded)
                self._ok(typ, data, f"COPY -> {target!r}")
                typ, data = self.imap.uid("STORE", uid_set, "+FLAGS.SILENT", "(\\Deleted)")
                self._ok(typ, data, "STORE \\Deleted")
                if self.has("UIDPLUS"):
                    typ, data = self.imap.uid("EXPUNGE", uid_set)
                    self._ok(typ, data, "UID EXPUNGE")
                else:
                    raise MailboxError(
                        f"Konto {self.account}: Server kann weder MOVE noch UID EXPUNGE. "
                        "Ein pauschales EXPUNGE waere zu riskant - abgebrochen, "
                        "es wurde nichts geloescht (die Kopien liegen bereits im Ziel)."
                    )

            moved += len(block)
            if progress:
                progress(moved, len(uids))
            time.sleep(PAUSE_SECONDS)

        self._log(f"{folder} -> {target}: {moved} verschoben")
        return moved

    def mark_seen(self, folder: str, uids: list[int]) -> int:
        """Als gelesen markieren - fuer Massen-Archivierung sinnvoll."""
        if not uids:
            return 0
        self.select(folder, readonly=False)
        for start in range(0, len(uids), CHUNK_MOVE):
            block = uids[start:start + CHUNK_MOVE]
            typ, data = self.imap.uid(
                "STORE", ",".join(str(u) for u in block), "+FLAGS.SILENT", "(\\Seen)")
            self._ok(typ, data, "STORE \\Seen")
            time.sleep(PAUSE_SECONDS)
        return len(uids)
