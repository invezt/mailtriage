"""Modified UTF-7 nach RFC 3501 (IMAP-Ordnernamen).

Python bringt diesen Codec nicht mit, Ordnernamen wie "Gelöschte Objekte"
oder "Archiv/Immobilien" brauchen ihn aber. Ohne das scheitert jedes
SELECT auf einem Ordner mit Umlaut.
"""

from __future__ import annotations

import binascii


def encode(name: str) -> bytes:
    """Python-String -> IMAP-UTF-7-Bytes."""
    out = bytearray()
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        raw = "".join(buffer).encode("utf-16-be")
        b64 = binascii.b2a_base64(raw, newline=False).rstrip(b"=")
        out.extend(b"&" + b64.replace(b"/", b",") + b"-")
        buffer.clear()

    for char in name:
        if char == "&":
            flush()
            out.extend(b"&-")
        elif "\x20" <= char <= "\x7e":
            flush()
            out.extend(char.encode("ascii"))
        else:
            buffer.append(char)
    flush()
    return bytes(out)


def decode(raw: bytes | str) -> str:
    """IMAP-UTF-7-Bytes -> Python-String."""
    if isinstance(raw, str):
        raw = raw.encode("ascii", "replace")

    out: list[str] = []
    buffer = bytearray()
    in_shift = False

    for byte in raw:
        char = chr(byte)
        if in_shift:
            if char == "-":
                if buffer:
                    padded = bytes(buffer).replace(b",", b"/")
                    padded += b"=" * (-len(padded) % 4)
                    try:
                        out.append(binascii.a2b_base64(padded).decode("utf-16-be"))
                    except (binascii.Error, UnicodeDecodeError):
                        # Kaputte Kodierung lieber roh durchreichen als abstürzen.
                        out.append("&" + bytes(buffer).decode("ascii", "replace"))
                    buffer.clear()
                else:
                    out.append("&")
                in_shift = False
            else:
                buffer.append(byte)
        elif char == "&":
            in_shift = True
            buffer.clear()
        else:
            out.append(char)

    if in_shift and buffer:
        out.append("&" + bytes(buffer).decode("ascii", "replace"))
    return "".join(out)
