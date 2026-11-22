"""Run in a venv that holds the wheel alone (no dev group, no extra): the core works there.

Not collected by pytest (no `test_` prefix). CI runs it as:
    python -I tests/core_only.py
It prints `core only: ok` or fails with an assertion.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# `yaml` is what the MCP skills reader brings (spec 005); the core must never load it.
FORBIDDEN = ("a2a", "mcp", "langchain", "langgraph", "yaml")


def main() -> None:
    import ext_r2c
    import ext_r2c.core  # noqa: F401

    assert ext_r2c.STANDARD_VERSION == "1"
    assert importlib.util.find_spec("rfc3339_validator") is None, (
        "rfc3339_validator is installed: this is not a core-only venv"
    )
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(FORBIDDEN))
    assert not loaded, f"importing the core loaded {loaded}"

    from ext_r2c.core import InvalidObject, parse, schema_kinds, to_json

    standard = _standard_dir()
    seen: dict[str, int] = {}
    for path in sorted((standard / "examples").glob("*/*.json")):
        if path.parent.name == "invalid":
            continue
        for obj in _objects(json.loads(path.read_text(encoding="utf-8"))):
            if obj["kind"] in schema_kinds():
                assert to_json(parse(obj)) == obj, f"{path.name}: {obj['kind']} changed"
                seen[obj["kind"]] = seen.get(obj["kind"], 0) + 1
    assert set(seen) == set(schema_kinds()), f"kinds seen: {sorted(seen)}"

    # Without rfc3339_validator, jsonschema would skip `date-time`; the core checks it itself.
    bad = json.loads((standard / "examples" / "invalid" / "question-expires-not-a-date.json").read_text())
    try:
        parse(bad["object"])
    except InvalidObject as e:
        assert "/expires_at" in [p for p, _ in e.errors], e.errors
    else:
        raise AssertionError("a question with expires_at 'not a date' was accepted")

    print("core only: ok")


def _standard_dir() -> Path:
    override = os.environ.get("R2C_STANDARD_DIR")
    path = Path(override) if override else Path(__file__).resolve().parents[2] / "standard" / "v1"
    assert path.is_dir(), f"standard folder not found at {path}"
    return path


def _objects(node: Any) -> Iterator[dict[str, Any]]:
    """Every JSON object with a string `kind` (enough for a smoke check of the six kinds)."""
    if isinstance(node, dict):
        if isinstance(node.get("kind"), str):
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _objects(item)


if __name__ == "__main__":
    main()
