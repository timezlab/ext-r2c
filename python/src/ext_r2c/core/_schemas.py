"""The packaged v1 schemas, the validators built on them, and JSON Pointer helpers.

The schemas are read from ``ext_r2c/schema/v1/`` inside the installed package, never from the
network. ``date-time`` is checked by this module's own function, because jsonschema skips the
format silently when the optional ``rfc3339_validator`` package is missing (research R3).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

_FILES = {
    "question": "question.json",
    "approval": "approval.json",
    "answer": "answer.json",
    "artifact": "artifact-meta.json",
    "activity": "activity.json",
    "usage": "usage.json",
}

_DATE_TIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-](\d{2}):(\d{2}))$"
)


def schema_kinds() -> tuple[str, ...]:
    """The six kinds that have a schema."""
    return tuple(_FILES)


@cache
def _load(kind: str) -> dict[str, Any]:
    data = (files("ext_r2c") / "schema" / "v1" / _FILES[kind]).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(data)
    return loaded


def schema(kind: str) -> dict[str, Any]:
    """A copy of the packaged schema of ``kind``; ``KeyError`` for a kind without one."""
    if kind not in _FILES:
        raise KeyError(f"no R2C schema for kind {kind!r}")
    return copy.deepcopy(_load(kind))


def is_date_time(value: object) -> bool:
    """RFC 3339 ``date-time``: a full date, a time and an offset. Non-strings pass (as JSON Schema says)."""
    if not isinstance(value, str):
        return True
    m = _DATE_TIME.match(value)
    if not m:
        return False
    year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
    try:
        datetime(year, month, day, hour, minute, min(second, 59))  # 60 is a leap second
    except ValueError:
        return False
    if second > 60:
        return False
    if m.group(9) is not None and (int(m.group(9)) > 23 or int(m.group(10)) > 59):
        return False
    return True


def format_checker() -> FormatChecker:
    """A format checker that knows ``date-time`` (the only format the v1 schemas use)."""
    checker = FormatChecker(formats=())
    checker.checks("date-time")(is_date_time)
    return checker


def validator(schema_: Mapping[str, Any]) -> Draft202012Validator:
    """A Draft 2020-12 validator for ``schema_`` with this module's format checker."""
    return Draft202012Validator(schema_, format_checker=format_checker())


@cache
def kind_validator(kind: str) -> Draft202012Validator:
    """The validator of a kind's packaged schema (built once)."""
    return validator(_load(kind))


def subschema_validator(root: Mapping[str, Any], name: str) -> Draft202012Validator:
    """A validator for ``root#/$defs/<name>``, with ``root``'s other ``$defs`` resolvable (R5)."""
    return validator({
        "$schema": root.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$defs": root.get("$defs", {}),
        "$ref": f"#/$defs/{name}",
    })


def external_refs(node: Any) -> list[str]:
    """Every ``$ref`` / ``$dynamicRef`` in a schema that leaves the document (R4)."""
    return [ref for ref in _refs(node) if not ref.startswith("#")]


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, Mapping):
        for k, v in node.items():
            if k in ("$ref", "$dynamicRef") and isinstance(v, str):
                yield v
            else:
                yield from _refs(v)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def pointer(parts: Any) -> str:
    """A JSON Pointer from path parts (``""`` is the whole document)."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def errors(v: Draft202012Validator, instance: Any) -> list[tuple[str, str]]:
    """``(pointer, message)`` for every error, including those nested in ``anyOf`` / ``oneOf``."""
    out: list[tuple[str, str]] = []

    def visit(err: Any) -> None:
        out.append((pointer(err.absolute_path), err.message))
        for sub in err.context or ():
            visit(sub)

    for err in sorted(v.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path))):
        visit(err)
    return out
