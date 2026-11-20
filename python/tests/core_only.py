"""Run in a venv that holds the wheel alone (no dev group, no extra): the core works there.

Not collected by pytest (no `test_` prefix). CI runs it as:
    python -I tests/core_only.py
It prints `core only: ok` or fails with an assertion.
"""

from __future__ import annotations

import importlib.util
import sys

FORBIDDEN = ("a2a", "mcp", "langchain", "langgraph")


def main() -> None:
    import ext_r2c
    import ext_r2c.core  # noqa: F401

    assert ext_r2c.STANDARD_VERSION == "1"
    assert importlib.util.find_spec("rfc3339_validator") is None, (
        "rfc3339_validator is installed: this is not a core-only venv"
    )
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(FORBIDDEN))
    assert not loaded, f"importing the core loaded {loaded}"

    # phase 2: parse one object of each kind from standard/v1/examples, and check that
    # invalid/question-expires-not-a-date.json is rejected without rfc3339_validator (T014).

    print("core only: ok")


if __name__ == "__main__":
    main()
