"""How a skill, a folder or a file is named on the wire (spec 005, research R3).

A URI is `skill://<segment>/<segment>/...`. Every segment is percent-encoded with nothing kept but
the unreserved characters, so a URI is pure ASCII and a `/` in it always separates segments. The
first segment is the URI's authority. A URI is only ever compared, as a whole string, with the
URIs the server serves; no code here or elsewhere builds a path on disk from one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import quote, unquote

SCHEME = "skill"
SKILL_FILE = "SKILL.md"

_PREFIX = f"{SCHEME}://"
MAX_NAME_LENGTH = 64
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def skill_name_ok(name: object) -> bool:
    """A skill `name`: 1 to 64 lowercase ASCII letters and digits, single hyphens inside, none at
    either end (`^[a-z0-9]+(-[a-z0-9]+)*$`; a v1 limit, stricter than the Unicode of agentskills.io)."""
    return isinstance(name, str) and len(name) <= MAX_NAME_LENGTH and _NAME.fullmatch(name) is not None


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


def authority_key(segments: Sequence[str]) -> str:
    """What decides that two first segments are one authority: the encoded segment with its ASCII
    letters lowered, as RFC 3986 compares a host. `Team` and `team` collide; `É` and `é` do not."""
    return _segment(segments[0]).lower()


def last_segments(uri: str, n: int) -> tuple[str, ...]:
    """The last `n` segments of a `skill://` URI, percent-decoded (all of them if there are fewer);
    nothing for a URI of another scheme. A query or a fragment is not split off: it stays part of
    the last segment, so a URI that has one never ends in `SKILL.md`."""
    if n <= 0 or not uri.startswith(_PREFIX):
        return ()
    return tuple(unquote(part) for part in uri[len(_PREFIX) :].split("/")[-n:])
