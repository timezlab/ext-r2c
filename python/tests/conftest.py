"""Shared fixtures: where the standard lives. A one-line count of the examples at the end."""

from pathlib import Path
from typing import Any

import pytest

from r2c_check import EnvelopeError, example_files, load_json, load_schemas, standard_path, unknown_kinds


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
    for p in valid:
        try:
            ignored += len(unknown_kinds(load_json(p), known))
        except (EnvelopeError, ValueError, KeyError):
            continue  # a broken example is already reported by its own test
    terminalreporter.write_line(
        f"R2C examples: {len(valid)} valid, {len(invalid)} invalid, {ignored} unknown kinds ignored"
    )
