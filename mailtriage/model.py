"""Datenmodell: eine Nachricht, wie sie aus den IMAP-Kopfzeilen entsteht.

Bewusst nur Kopfzeilen - der Rumpf wird nie geladen. Das ist der Grund,
warum auch 20.000 Mails hier kein Speicher- oder Stabilitaetsproblem sind.
"""

from __future__ import annotations

import email.errors
import email.header
import email.utils
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Kopfzeilen, die wir anfordern. Alles andere bleibt auf dem Server.
HEADER_FIELDS = (
    "FROM",
    "TO",
    "CC",
    "SUBJECT",
    "DATE",
    "REPLY-TO",
    "LIST-ID",
    "LIST-UNSUBSCRIBE",
    "MESSAGE-ID",
    "X-SPAM-FLAG",
    "AUTHENTICATION-RESULTS",
)

_WS = re.compile(r"\s+")


def decode_header(value) -> str:
    """MIME-kodierte Kopfzeile ("=?utf-8?B?...?=") in lesbaren Text.

    Alte Postfaecher enthalten Kopfzeilen mit kaputten oder unbekannten
    Zeichensaetzen. Keine davon darf einen Lauf abbrechen - im Zweifel wird
    ersetzt statt abgebrochen.
    """
    if not value:
        return ""
    if not isinstance(value, str):
        # email liefert bei undekodierbaren Bytes ein Header-Objekt.
        try:
            value = str(value)
        except (UnicodeError, email.errors.MessageError):
            return ""

    parts: list[str] = []
    try:
        stuecke = email.header.decode_header(value)
    except (email.errors.HeaderParseError, ValueError):
        return _WS.sub(" ", value).strip()

    for chunk, charset in stuecke:
        if not isinstance(chunk, bytes):
            parts.append(chunk)
            continue
        try:
            parts.append(chunk.decode(charset or "utf-8", "replace"))
        except (LookupError, UnicodeError):
            # Unbekannter Zeichensatz wie "unknown-8bit": auf utf-8 ausweichen.
            parts.append(chunk.decode("utf-8", "replace"))
    return _WS.sub(" ", "".join(parts)).strip()


def split_address(value: str) -> tuple[str, str]:
    """"Max Muster <max@example.com>" -> ("Max Muster", "max@example.com")."""
    name, addr = email.utils.parseaddr(value or "")
    return decode_header(name), addr.strip().lower()


def domain_of(address: str) -> str:
    _, _, domain = address.partition("@")
    return domain.strip().lower()


@dataclass
class Message:
    """Eine Nachricht, reduziert auf das, was fuer die Triage zaehlt."""

    account: str
    folder: str
    uid: int
    date: datetime
    size: int
    flags: tuple[str, ...] = ()
    from_name: str = ""
    from_addr: str = ""
    subject: str = ""
    to_addrs: tuple[str, ...] = ()
    list_id: str = ""
    has_unsubscribe: bool = False
    message_id: str = ""
    spam_flagged: bool = False
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def from_domain(self) -> str:
        return domain_of(self.from_addr)

    @property
    def seen(self) -> bool:
        return "\\Seen" in self.flags

    @property
    def answered(self) -> bool:
        return "\\Answered" in self.flags

    @property
    def flagged(self) -> bool:
        return "\\Flagged" in self.flags

    @property
    def is_bulk(self) -> bool:
        """Massenversand: Newsletter, Werbung, Listen."""
        return self.has_unsubscribe or bool(self.list_id)

    def age_days(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.date).total_seconds() / 86400.0

    def sender_label(self) -> str:
        return self.from_name or self.from_addr or "(kein Absender)"


def parse_headers(
    account: str,
    folder: str,
    uid: int,
    internaldate: datetime,
    size: int,
    flags: tuple[str, ...],
    raw_headers: bytes,
) -> Message:
    """Baut aus dem rohen Kopfzeilen-Block eine Message."""
    parsed = email.message_from_bytes(raw_headers)
    headers = {k.lower(): decode_header(v) for k, v in parsed.items()}

    from_name, from_addr = split_address(parsed.get("From", ""))

    to_addrs: list[str] = []
    for header_name in ("To", "Cc"):
        for _, addr in email.utils.getaddresses(parsed.get_all(header_name) or []):
            if addr:
                to_addrs.append(addr.strip().lower())

    spam_flagged = (headers.get("x-spam-flag", "").lower().startswith("y")
                    or "dmarc=fail" in headers.get("authentication-results", "").lower())

    return Message(
        account=account,
        folder=folder,
        uid=uid,
        date=internaldate,
        size=size,
        flags=flags,
        from_name=from_name,
        from_addr=from_addr,
        subject=decode_header(parsed.get("Subject", "")),
        to_addrs=tuple(dict.fromkeys(to_addrs)),
        list_id=headers.get("list-id", ""),
        has_unsubscribe=bool(parsed.get("List-Unsubscribe")),
        message_id=(parsed.get("Message-ID") or "").strip(),
        spam_flagged=spam_flagged,
        headers=headers,
    )
