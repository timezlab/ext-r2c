"""The installed wheel: its extras, and the import rules of `ext_r2c.core` and `ext_r2c.a2a`
(constitution VIII)."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from importlib.metadata import metadata
from importlib.resources import files

ALLOWED_TOP_LEVEL = {"pydantic", "pydantic_core", "jsonschema", "ext_r2c"}
FORBIDDEN = ("a2a", "mcp", "langchain", "langgraph")
# What `a2a-sdk[http-server]` brings, besides the core's own (research R15).
A2A_ALLOWED_TOP_LEVEL = ALLOWED_TOP_LEVEL | {"a2a", "google", "httpx", "starlette", "sse_starlette"}


def _imports(package: str) -> list[tuple[str, int, str]]:
    """(file, line, module) for every absolute import in the installed `ext_r2c/<package>/`."""
    folder = files("ext_r2c") / package
    assert folder.is_dir(), f"ext_r2c/{package} is not in the installed wheel"
    found: list[tuple[str, int, str]] = []
    for item in folder.iterdir():
        if not item.name.endswith(".py"):
            continue
        tree = ast.parse(item.read_text(encoding="utf-8"), filename=item.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [(item.name, node.lineno, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                found.append((item.name, node.lineno, node.module or ""))
    return found


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
    a2a = [
        r.split(";", 1)[0].replace(" ", "") for r in meta.get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']a2a["']""", r)
    ]
    assert len(a2a) == 1, a2a
    head = a2a[0]
    assert head.startswith("a2a-sdk[http-server]"), head
    assert ">=1.3" in head and "<2" in head, head


def _bad_imports(package: str, allowed: set[str]) -> list[str]:
    bad: list[str] = []
    for file, line, name in _imports(package):
        top = name.split(".")[0]
        if top not in sys.stdlib_module_names and top not in allowed:
            bad.append(f"{file}:{line} {name}")
        elif top == "ext_r2c" and not name.startswith("ext_r2c.core") and name != "ext_r2c":
            bad.append(f"{file}:{line} {name} (imports another door, a bridge or remote)")
    return bad


def test_core_imports_only_allowed_modules() -> None:
    bad = _bad_imports("core", ALLOWED_TOP_LEVEL)
    assert not bad, "core imports outside stdlib, pydantic, jsonschema:\n" + "\n".join(bad)


def test_a2a_imports_only_allowed_modules() -> None:
    bad = _bad_imports("a2a", A2A_ALLOWED_TOP_LEVEL)
    assert not bad, "a2a imports outside core and a2a-sdk[http-server]:\n" + "\n".join(bad)


def test_a2a_import_loads_no_other_door() -> None:
    code = (
        "import sys, ext_r2c.a2a; "
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'mcp', 'langchain', 'langgraph'}))"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_core_import_loads_no_protocol_sdk() -> None:
    code = (
        "import sys, ext_r2c.core; "
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {set(FORBIDDEN)!r}))"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
