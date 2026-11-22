"""The page cursor of `skills/list` and `resources/directory/read` (spec 005, research R9).

A cursor is opaque to the caller: base64url (no padding) of `<generation>.<offset>`. The
generation names one listing of one catalogue (the extension passes the catalogue's own token for
`skills/list` and that token with a hash of the URI for one directory), so a cursor from before a
refresh, from another server or from another listing is refused instead of pointing into a different
list and skipping or repeating entries. A cursor carries no path and grants nothing.
"""

from __future__ import annotations

import base64

MAX_CURSOR_LENGTH = 256


class CursorError(ValueError):
    """The cursor is not one this catalogue issued. The message is fixed: it never echoes input."""

    def __init__(self) -> None:
        super().__init__("Invalid cursor")

    def __reduce__(self) -> tuple[type[CursorError], tuple[()]]:
        return (type(self), ())


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_cursor(generation: str, offset: int) -> str:
    """The cursor for the page that starts at `offset` in the catalogue `generation`."""
    if not generation or "." in generation:
        raise ValueError("a generation is a non-empty token without a dot")
    if offset < 0:
        raise ValueError("an offset is not negative")
    return _encode(f"{generation}.{offset}".encode())


def decode_cursor(cursor: str, generation: str, total: int) -> int:
    """The offset a cursor stands for, or `CursorError`: not a cursor this code issues, one of
    another generation, or one that points at or past the end of `total` entries."""
    if len(cursor) > MAX_CURSOR_LENGTH:
        raise CursorError
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        text = raw.decode("ascii")
    except ValueError:  # binascii.Error and UnicodeDecodeError are both ValueErrors
        raise CursorError from None
    # The decoder skips characters outside the alphabet and accepts extra padding; only the exact
    # form this module writes is a cursor.
    if _encode(raw) != cursor:
        raise CursorError
    # `text` is ASCII (decoded above), so `isdigit` means 0-9 only; no dot leaves `digits` empty.
    found, _, digits = text.partition(".")
    if found != generation or not digits.isdigit() or str(int(digits)) != digits:
        raise CursorError
    offset = int(digits)
    if offset >= total:
        raise CursorError
    return offset
