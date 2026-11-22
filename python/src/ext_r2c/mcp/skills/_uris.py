"""How a skill, a folder or a file is named on the wire (spec 005, research R3).

A URI this package builds is `skill://<segment>/<segment>/...`. Every segment is percent-encoded with
nothing kept but the unreserved characters, so a URI is pure ASCII and a `/` in it always separates
segments. The first segment is the URI's authority. A URI is only ever compared, as a whole string,
with the URIs the server serves; no code here or elsewhere builds a path on disk from one.

A server may use another scheme (the extension privileges none), so what is read from a URI here
accepts any `<scheme>://`; the structural rules (the segments) hold for all of them.

`skill_name_ok`, `name_unsafe` and `segment_ok` are the one copy of what a name may be: the server leaves
out what they refuse, and the client refuses an entry or a directory request that has it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from urllib.parse import quote, unquote

from ._limits import MAX_NAME_LENGTH

SCHEME = "skill"
SKILL_FILE = "SKILL.md"

_PREFIX = f"{SCHEME}://"
_SCHEME_AND_SLASHES = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Format characters (not Control, Line or Paragraph separators by category) that only reorder text: the
# Arabic letter mark, the left-to-right and right-to-left marks, the embeddings and overrides
# (U+202A to U+202E) and the isolates (U+2066 to U+2069).
_BIDI = frozenset([0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)])
_UNSAFE_CATEGORIES = frozenset(["Cc", "Zl", "Zp"])


def skill_name_ok(name: object) -> bool:
    """A skill `name` this package serves: 1 to 64 lowercase ASCII letters and digits, single hyphens
    inside, none at either end (`^[a-z0-9]+(-[a-z0-9]+)*$`; a v1 limit, stricter than the Unicode of
    agentskills.io)."""
    return isinstance(name, str) and len(name) <= MAX_NAME_LENGTH and _NAME.fullmatch(name) is not None


def char_unsafe(char: str) -> bool:
    """A character that is never part of a name this package serves or accepts: a control character, a
    line or paragraph separator, a bidirectional control, or a backslash (a path separator on
    Windows). Text in any script, a combining mark and a zero-width joiner are not unsafe."""
    return char == "\\" or ord(char) in _BIDI or unicodedata.category(char) in _UNSAFE_CATEGORIES


def name_unsafe(name: str) -> bool:
    """`name` holds an unsafe character (`char_unsafe`)."""
    return any(char_unsafe(char) for char in name)


def segment_ok(segment: str) -> bool:
    """A segment of a URI, as it is sent (percent-encoded), is something a name decodes from: not empty,
    not `.` or `..` and no `/`, no unsafe character, each after one percent-decoding."""
    decoded = unquote(segment)
    return bool(segment) and decoded not in (".", "..") and "/" not in decoded and not name_unsafe(decoded)


def _segment(segment: str) -> str:
    if segment in ("", ".", ".."):
        raise ValueError(f"{segment!r} does not name a folder or a file")
    return quote(segment, safe="")


def encode_uri(segments: Sequence[str], file: str | Sequence[str] | None = None) -> str:
    """The URI of a skill folder (`segments`), or of what is inside it: `file` is one name or the
    names from the folder down. No trailing slash."""
    if not segments:
        raise ValueError("a skill path has at least one segment")
    parts = list(segments)
    if file is not None:
        parts.extend([file] if isinstance(file, str) else file)
    return _PREFIX + "/".join(_segment(part) for part in parts)


def fold_authority(uri: str) -> str:
    """The URI with the ASCII letters of its first segment lowered, as RFC 3986 compares a host: what
    decides that two URIs have one authority. `Team` and `team` collide; `É` and `é` do not."""
    authority, slash, rest = uri.removeprefix(_PREFIX).partition("/")
    return f"{_PREFIX}{authority.lower()}{slash}{rest}"


def last_segments(uri: str, n: int) -> tuple[str, ...]:
    """The last `n` segments of a `<scheme>://` URI, percent-decoded (all of them if there are fewer);
    nothing for a URI that does not begin with a scheme and two slashes. A query or a fragment is not
    split off: it stays part of the last segment, so a URI that has one never ends in `SKILL.md`."""
    found = _SCHEME_AND_SLASHES.match(uri)
    if n <= 0 or found is None:
        return ()
    return tuple(unquote(part) for part in uri[found.end() :].split("/")[-n:])
