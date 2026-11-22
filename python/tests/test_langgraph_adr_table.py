"""The ADR of the LangGraph bridge names the tests that prove each decision: every name must exist.

A test that is renamed or removed leaves the ADR pointing at nothing; this fails when that happens (spec 006
phase 10, where three names had gone stale). Skipped when the tests run from an installed wheel with no
repository checkout beside them.
"""

import ast
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ADR = _HERE.parents[1] / "docs" / "design-docs" / "langgraph-pause-to-ask.md"
_NAME = re.compile(r"`(test_[A-Za-z0-9_]+)`")


def _defined() -> set[str]:
    """Every function named `test_*` defined in any module of this folder, at any depth."""
    found: set[str] = set()
    for path in _HERE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        )
    return found


def test_the_adr_names_only_tests_that_exist() -> None:
    if not _ADR.is_file():
        pytest.skip("no repository checkout beside the tests")
    named = set(_NAME.findall(_ADR.read_text(encoding="utf-8")))
    assert named, "the ADR names no test: its table is the map from a decision to its proof"
    missing = sorted(named - _defined())
    assert not missing, f"the ADR names tests that do not exist: {missing}"
