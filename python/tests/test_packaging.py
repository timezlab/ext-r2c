"""The installed wheel: its extras, and the import rules of `ext_r2c.core` (constitution VIII)."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from importlib.metadata import metadata
from importlib.resources import files

ALLOWED_TOP_LEVEL = {"pydantic", "pydantic_core", "jsonschema", "ext_r2c"}
FORBIDDEN = ("a2a", "mcp", "langchain", "langgraph")


def _requirement_name(req: str) -> str:
    """`a2a-sdk>=1.3; extra == "a2a"` → `a2a-sdk`; `ext-r2c[a2a]` → `ext-r2c[a2a]`."""
    head = req.split(";", 1)[0].strip()
    return re.split(r"[<>=!~ (]", head, maxsplit=1)[0]


def test_extras() -> None:
    meta = metadata("ext-r2c")
    assert set(meta.get_all("Provides-Extra") or []) == {"a2a", "mcp", "langgraph"}
    langgraph = [
        _requirement_name(r) for r in meta.get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']langgraph["']""", r)
    ]
    assert langgraph, "the langgraph extra requires nothing"
    assert not [n for n in langgraph if n.startswith(("a2a-sdk", "ext-r2c"))], langgraph


def test_core_imports_only_allowed_modules() -> None:
    core = files("ext_r2c") / "core"
    assert core.is_dir(), "ext_r2c/core is not in the installed wheel"
    bad: list[str] = []
    for item in core.iterdir():
        if not item.name.endswith(".py"):
            continue
        tree = ast.parse(item.read_text(encoding="utf-8"), filename=item.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # relative import, inside the package
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top not in sys.stdlib_module_names and top not in ALLOWED_TOP_LEVEL:
                    bad.append(f"{item.name}:{node.lineno} {name}")
                elif top == "ext_r2c" and not name.startswith("ext_r2c.core") and name != "ext_r2c":
                    bad.append(f"{item.name}:{node.lineno} {name} (core imports no door or bridge)")
    assert not bad, "core imports outside stdlib, pydantic, jsonschema:\n" + "\n".join(bad)


def test_core_import_loads_no_protocol_sdk() -> None:
    code = (
        "import sys, ext_r2c.core; "
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {set(FORBIDDEN)!r}))"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
