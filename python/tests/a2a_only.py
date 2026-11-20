"""Run in a venv that holds the wheel with the `[a2a]` extra only (no dev group): the A2A door
works there and loads no other door or bridge (constitution VIII).

Not collected by pytest (no `test_` prefix). CI runs it as:
    python -I tests/a2a_only.py
It prints `a2a only: ok` or fails with an assertion.
"""

from __future__ import annotations

import importlib.util
import sys

OTHERS = ("mcp", "langchain", "langgraph")


def main() -> None:
    import ext_r2c.a2a  # noqa: F401

    assert importlib.util.find_spec("pytest") is None, "pytest is installed: this is not an a2a-only venv"
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"importing the A2A door loaded {loaded}"

    # phase 3: build agent_card and a2a_app for a trivial source (T030)

    print("a2a only: ok")


if __name__ == "__main__":
    main()
