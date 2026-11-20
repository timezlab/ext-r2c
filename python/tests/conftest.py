"""Shared fixtures: where the standard lives. A one-line count of the examples at the end."""

from pathlib import Path
from typing import Any

import pytest

from r2c_check import (
    EnvelopeError,
    example_files,
    find_r2c_objects,
    load_json,
    load_schemas,
    standard_path,
    unknown_kinds,
)


@pytest.fixture(scope="session")
def standard_dir() -> Path:
    """The `standard/v1` folder of the repository checkout (or `R2C_STANDARD_DIR`)."""
    path = standard_path()
    if not path.is_dir():
        pytest.fail(
            f"standard folder not found at {path}; run the tests from a repository checkout "
            "or set R2C_STANDARD_DIR",
            pytrace=False,
        )
    return path


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Report N valid examples, M invalid examples and K ignored unknown kinds (quickstart 1)."""
    path = standard_path()
    if not path.is_dir():
        return
    valid = example_files("a2a") + example_files("mcp")
    invalid = example_files("invalid")
    known = set(load_schemas(path))
    ignored = 0
    round_tripped = 0
    for p in valid:
        try:
            example = load_json(p)
            ignored += len(unknown_kinds(example, known))
            round_tripped += _round_trips(example, known)
        except (EnvelopeError, ValueError, KeyError, ImportError):
            continue  # a broken example (or core) is already reported by its own test
    terminalreporter.write_line(
        f"R2C examples: {len(valid)} valid, {len(invalid)} invalid, {ignored} unknown kinds ignored; "
        f"{round_tripped} objects round-tripped"
    )


def _round_trips(example: Any, known: set[str]) -> int:
    """How many known-kind objects of one example come back unchanged through the core models."""
    from ext_r2c.core import parse, to_json

    count = 0
    for n, step in enumerate(example["steps"]):
        for _, obj in find_r2c_objects(example["binding"], step["body"], f"/steps/{n}/body"):
            if obj["kind"] in known and to_json(parse(obj)) == obj:
                count += 1
    return count
