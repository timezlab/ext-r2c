"""The YAML header of a `SKILL.md`, read as plain JSON data (spec 005, research R7).

A skill's frontmatter is YAML, and MCP Skills passes it on "verbatim" as JSON. This reader is the
one place that parses it, on the server (to build an entry) and in the caller's client (to check
an entry against the file it fetched), so both read a header the same way.

It is deliberately smaller than YAML. A header is **data**: it builds only strings, numbers,
booleans, null, lists and mappings with string keys, and it refuses everything that would make
reading it expensive or ambiguous:

- an anchor, an alias or a merge key (so no document can grow when it is read);
- a tag it does not know (so no document can build a Python object);
- a duplicate key (PyYAML keeps the last one without a word);
- a number or boolean written in the dialects of YAML 1.1. A plain scalar is a number only if it is
  JSON-like (`3`, `-4`, `1.5`, `2.5e3`) and a boolean only if it is `true` or `false`, so `yes`,
  `no`, `on`, `off`, `12:30`, `0755`, `0x1f`, `1_000` and a date such as `2026-01-02` stay the text
  the author wrote (a quoted scalar is always text, and an explicit core tag such as `!!int` is
  accepted for what it says); `.inf` and `.nan` are refused;
- a header over 64 KiB or nested deeper than `MAX_DEPTH`.

A failure is a `FrontmatterError` whose `reason` comes from the fixed set `REASONS`. The message
is that reason and nothing else: it never carries the text of the file, a line of it or a path.
"""

from __future__ import annotations

import math
import re
from typing import Any

import yaml

#: A guard of this package, not of the protocol: the frontmatter text, in UTF-8 bytes.
MAX_FRONTMATTER_BYTES = 64 * 1024
#: Containers inside containers, the top-level mapping counted as the first.
MAX_DEPTH = 32

#: What a `FrontmatterError.reason` can be.
REASONS = frozenset(
    {
        "missing",  # the file does not start with a line that is exactly `---`
        "unclosed",  # no later line is exactly `---`
        "not utf-8",
        "too large",
        "syntax error",  # YAML that does not parse, and any failure that is not one of the others
        "duplicate key",
        "anchor or alias",
        "merge key",
        "unknown tag",
        "not a mapping",
        "non-string key",
        "not json",  # a number that is not finite, or text that JSON cannot carry
        "too deep",
    }
)


class FrontmatterError(ValueError):
    """The frontmatter of a `SKILL.md` cannot be read; `reason` is one of `REASONS`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Refused(Exception):
    """A refusal made inside the loader; it never leaves this module."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_NULL = "tag:yaml.org,2002:null"
_BOOL = "tag:yaml.org,2002:bool"
_INT = "tag:yaml.org,2002:int"
_FLOAT = "tag:yaml.org,2002:float"
_STR = "tag:yaml.org,2002:str"
_SEQ = "tag:yaml.org,2002:seq"
_MAP = "tag:yaml.org,2002:map"

# The only plain scalars that are not text. `\Z`, not `$`: a value never ends in a newline.
_BOOL_RE = re.compile(r"(?:true|True|TRUE|false|False|FALSE)\Z")
_INT_RE = re.compile(r"[-+]?(?:0|[1-9][0-9]*)\Z")
_FLOAT_RE = re.compile(
    r"(?:[-+]?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][-+]?[0-9]+)?|[eE][-+]?[0-9]+)"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))\Z"  # kept only to be refused after loading
)


def _implicit_resolvers() -> dict[str | None, list[tuple[str, re.Pattern[str]]]]:
    """PyYAML's `null`, then the three patterns above: no timestamp, no `value`, no merge."""
    table: dict[str | None, list[tuple[str, re.Pattern[str]]]] = {}
    for first, entries in yaml.SafeLoader.yaml_implicit_resolvers.items():
        kept = [(tag, pattern) for tag, pattern in entries if tag == _NULL]
        if kept:
            table[first] = kept
    for tag, pattern, firsts in (
        (_BOOL, _BOOL_RE, "tTfF"),
        (_INT, _INT_RE, "-+0123456789"),
        (_FLOAT, _FLOAT_RE, "-+0123456789."),
    ):
        for first in firsts:
            table.setdefault(first, []).append((tag, pattern))
    return table


def _undefined(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    raise _Refused("unknown tag")


class _Loader(yaml.SafeLoader):
    """`SafeLoader` (pure Python, not the C one) cut down to data, as the module docstring says."""

    yaml_implicit_resolvers = _implicit_resolvers()
    yaml_constructors = {
        **{
            tag: construct
            for tag, construct in yaml.SafeLoader.yaml_constructors.items()
            if tag in (_NULL, _BOOL, _INT, _FLOAT, _STR, _SEQ, _MAP)
        },
        None: _undefined,
    }

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        event = self.peek_event()
        if event.anchor is not None:  # an anchor, or an alias (whose `anchor` is the name it uses)
            raise _Refused("anchor or alias")
        nests = isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent))
        if nests:
            self._depth += 1
            if self._depth > MAX_DEPTH:
                raise _Refused("too deep")
        try:
            return super().compose_node(parent, index)
        finally:
            if nests:
                self._depth -= 1

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.style is None and key_node.value == "<<":
                raise _Refused("merge key")
            if not (isinstance(key_node, yaml.ScalarNode) and key_node.tag == _STR):
                raise _Refused("non-string key")
            key = self.construct_scalar(key_node)
            if key in mapping:
                raise _Refused("duplicate key")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_BOM = chr(0xFEFF)  # the byte-order mark, as the character a UTF-8 decoder leaves at the start

# A closing fence: a line that is exactly `---` (a carriage return before the newline is allowed).
_CLOSING = re.compile(r"^---\r?$", re.MULTILINE)


def read_frontmatter(data: bytes | str) -> dict[str, Any]:
    """The frontmatter of a `SKILL.md` (its bytes or its text) as a mapping, or a `FrontmatterError`.

    The frontmatter is the text between the opening `---` line (after an optional UTF-8 byte-order
    mark) and the next line that is exactly `---`. The body after it is ignored, but the whole file
    must be UTF-8.
    """
    front = _cut(_text(data))
    try:
        loaded = yaml.load(front, Loader=_Loader)  # noqa: S506  # a restricted SafeLoader (see above)
        if not isinstance(loaded, dict):
            raise _Refused("not a mapping")
        _check_json(loaded)
    except _Refused as refusal:
        raise FrontmatterError(refusal.reason) from None
    except RecursionError:
        raise FrontmatterError("too deep") from None
    except Exception:
        # A YAML error says where and shows the text; a failure of any other kind says nothing
        # safe either. The reason is all a caller gets.
        raise FrontmatterError("syntax error") from None
    return loaded  # type: ignore[no-any-return]


def _text(data: bytes | str) -> str:
    if isinstance(data, str):
        text = data
    else:
        try:
            text = bytes(data).decode("utf-8")
        except UnicodeDecodeError:
            raise FrontmatterError("not utf-8") from None
    return text.removeprefix(_BOM)  # one UTF-8 byte-order mark, if the file starts with it


def _cut(text: str) -> str:
    """The text between the fences, or the reason there are none."""
    first, _, rest = text.partition("\n")
    if first not in ("---", "---\r"):
        raise FrontmatterError("missing")
    closing = _CLOSING.search(rest)
    if closing is None:
        raise FrontmatterError("unclosed")
    front = rest[: closing.start()]
    try:
        size = len(front.encode("utf-8"))
    except UnicodeEncodeError:
        raise FrontmatterError("not utf-8") from None
    if size > MAX_FRONTMATTER_BYTES:
        raise FrontmatterError("too large")
    return front


def _check_text(text: str) -> None:
    try:
        text.encode("utf-8")  # a lone surrogate cannot be sent as JSON
    except UnicodeEncodeError:
        raise _Refused("not json") from None


def _check_json(value: object) -> None:
    """What the loader built must be JSON. The loader cannot build anything else today; this check
    keeps a later change to it from putting a Python object on the wire."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _Refused("non-string key")
            _check_text(key)
            _check_json(item)
    elif isinstance(value, list):
        for item in value:
            _check_json(item)
    elif isinstance(value, str):
        _check_text(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _Refused("not json")
    elif not (value is None or isinstance(value, (bool, int))):
        raise _Refused("not json")
