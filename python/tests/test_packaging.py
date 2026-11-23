"""The installed wheel: its extras, and the import rules of `ext_r2c.core`, `ext_r2c.a2a`,
`ext_r2c.mcp` and `ext_r2c.bridges.langgraph` (constitution VIII)."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections.abc import Iterator
from importlib.metadata import metadata
from importlib.resources import files
from importlib.resources.abc import Traversable

import pytest

ALLOWED_TOP_LEVEL = {"pydantic", "pydantic_core", "jsonschema", "ext_r2c"}
FORBIDDEN = ("a2a", "mcp", "langchain", "langchain_core", "langgraph")
# What the `langgraph` extra brings that the bridge may import (spec 006, research R18): the graph
# library and the message types. `langchain` itself is not imported: the payloads the bridge reads
# are plain data.
LANGGRAPH_ALLOWED_TOP_LEVEL = ALLOWED_TOP_LEVEL | {"langgraph", "langchain_core"}
# What `a2a-sdk[http-server]` brings, besides the core's own (research R15).
A2A_ALLOWED_TOP_LEVEL = ALLOWED_TOP_LEVEL | {"a2a", "google", "httpx", "starlette", "sse_starlette"}
# What `mcp` brings that the MCP door may use (spec 004, research R17), and `PyYAML`, which the
# skills reader needs (spec 005, research R7).
MCP_ALLOWED_TOP_LEVEL = ALLOWED_TOP_LEVEL | {"mcp", "mcp_types", "anyio", "httpx2", "starlette", "yaml"}


def _sources(folder: Traversable, prefix: str = "") -> Iterator[tuple[str, Traversable]]:
    """(path below the package folder, file) for every `.py` file, sub-folders included."""
    for item in sorted(folder.iterdir(), key=lambda i: i.name):
        if item.is_dir():
            if item.name != "__pycache__":
                yield from _sources(item, f"{prefix}{item.name}/")
        elif item.name.endswith(".py"):
            yield f"{prefix}{item.name}", item


def _imports(*package: str) -> list[tuple[str, int, str]]:
    """(file, line, module) for every absolute import in the installed `ext_r2c/<package>/`;
    `package` is the folder's segments (`"bridges", "langgraph"`), not a slash path."""
    folder = files("ext_r2c")
    for segment in package:
        folder = folder / segment
    where = "/".join(package)
    assert folder.is_dir(), f"ext_r2c/{where} is not in the installed wheel"
    found: list[tuple[str, int, str]] = []
    for name, item in _sources(folder):
        tree = ast.parse(item.read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [(name, node.lineno, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                found.append((name, node.lineno, node.module or ""))
    return found


def _requirement_name(req: str) -> str:
    """`a2a-sdk>=1.3; extra == "a2a"` → `a2a-sdk`; `ext-r2c[a2a]` → `ext-r2c[a2a]`."""
    head = req.split(";", 1)[0].strip()
    return re.split(r"[<>=!~ (]", head, maxsplit=1)[0]


def test_extras() -> None:
    meta = metadata("ext-r2c")
    assert set(meta.get_all("Provides-Extra") or []) == {"a2a", "mcp", "langgraph"}
    langgraph = [
        r.split(";", 1)[0].replace(" ", "") for r in meta.get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']langgraph["']""", r)
    ]
    # Spec 006, research R1: the graph library, the message library and the agent library, each
    # bounded on both sides (1.4.6 is the first `langchain` with the `per_call` middleware mode;
    # 1.2.14 is the first `langgraph` past GHSA-3fx2-cqw9-xr3c). No checkpointer: the owner brings it.
    assert len(langgraph) == 3, langgraph
    lg_by_name = {_requirement_name(r).lower(): r for r in langgraph}
    assert set(lg_by_name) == {"langchain", "langchain-core", "langgraph"}, langgraph
    assert ">=1.4.6" in lg_by_name["langchain"] and "<2" in lg_by_name["langchain"], lg_by_name["langchain"]
    assert ">=1.6.10" in lg_by_name["langchain-core"] and "<2" in lg_by_name["langchain-core"], lg_by_name
    assert ">=1.2.14" in lg_by_name["langgraph"] and "<2" in lg_by_name["langgraph"], lg_by_name["langgraph"]
    assert not [n for n in lg_by_name if n.startswith(("langgraph-checkpoint", "a2a-sdk", "ext-r2c"))]
    a2a = [
        r.split(";", 1)[0].replace(" ", "") for r in meta.get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']a2a["']""", r)
    ]
    assert len(a2a) == 1, a2a
    head = a2a[0]
    assert head.startswith("a2a-sdk[http-server]"), head
    assert ">=1.3" in head and "<2" in head, head
    mcp = [
        r.split(";", 1)[0].replace(" ", "") for r in meta.get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']mcp["']""", r)
    ]
    # The skills reader needs PyYAML (spec 005, research R7): a bound on both sides, like `mcp`.
    assert len(mcp) == 2, mcp
    by_name = {_requirement_name(r).lower(): r for r in mcp}  # the wheel writes names in lower case
    assert set(by_name) == {"mcp", "pyyaml"}, mcp
    assert ">=2.3" in by_name["mcp"] and "<3" in by_name["mcp"], by_name["mcp"]
    assert ">=6.0.3" in by_name["pyyaml"] and "<7" in by_name["pyyaml"], by_name["pyyaml"]


def _bad_imports(package: str | tuple[str, ...], allowed: set[str]) -> list[str]:
    bad: list[str] = []
    segments = (package,) if isinstance(package, str) else package
    for file, line, name in _imports(*segments):
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


def test_mcp_imports_only_allowed_modules() -> None:
    bad = _bad_imports("mcp", MCP_ALLOWED_TOP_LEVEL)
    assert not bad, "mcp imports outside core and what the mcp extra brings:\n" + "\n".join(bad)


def test_mcp_import_loads_no_other_door() -> None:
    code = (
        "import sys, ext_r2c.mcp; "
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'a2a', 'langchain', 'langgraph'}))"
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


def test_mcp_skills_imports_no_ext_r2c() -> None:
    """The skills package stands alone (spec 005, research R12): nothing of `ext_r2c` comes in,
    neither by name nor by a relative import that climbs out of `ext_r2c/mcp/skills/`."""
    folder = files("ext_r2c") / "mcp" / "skills"
    assert folder.is_dir(), "ext_r2c/mcp/skills is not in the installed wheel"
    bad: list[str] = []
    for name, item in _sources(folder):
        depth = name.count("/")  # sub-folders below `skills/`; a file there may climb `depth` levels
        for node in ast.walk(ast.parse(item.read_text(encoding="utf-8"), filename=name)):
            if isinstance(node, ast.Import):
                bad += [f"{name}:{node.lineno} {a.name}" for a in node.names if a.name.split(".")[0] == "ext_r2c"]
            elif isinstance(node, ast.ImportFrom):
                if node.level > depth + 1:
                    bad.append(f"{name}:{node.lineno} {'.' * node.level}{node.module or ''} (climbs out)")
                elif not node.level and (node.module or "").split(".")[0] == "ext_r2c":
                    bad.append(f"{name}:{node.lineno} {node.module}")
    assert not bad, "ext_r2c/mcp/skills imports ext_r2c:\n" + "\n".join(bad)


def test_core_import_loads_no_yaml() -> None:
    code = "import sys, ext_r2c, ext_r2c.core; print('yaml' in sys.modules)"
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_langgraph_bridge_imports_only_allowed_modules() -> None:
    """Spec 006, FR-004: the bridge imports the core, the extra's two packages and the core's own
    dependencies; an `ext_r2c` import starts with `ext_r2c.core` (the shared rule of `_bad_imports`),
    and no relative import climbs out of `ext_r2c/bridges/langgraph/`."""
    bad = _bad_imports(("bridges", "langgraph"), LANGGRAPH_ALLOWED_TOP_LEVEL)
    folder = files("ext_r2c") / "bridges" / "langgraph"
    for name, item in _sources(folder):
        depth = name.count("/")
        for node in ast.walk(ast.parse(item.read_text(encoding="utf-8"), filename=name)):
            if isinstance(node, ast.ImportFrom) and node.level > depth + 1:
                bad.append(f"{name}:{node.lineno} {'.' * node.level}{node.module or ''} (climbs out)")
    assert not bad, "bridges/langgraph imports outside core and the langgraph extra:\n" + "\n".join(bad)


def test_bridges_package_imports_nothing() -> None:
    """`ext_r2c/bridges/__init__.py` is a docstring: importing it must not load any bridge."""
    init = files("ext_r2c") / "bridges" / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"), filename="bridges/__init__.py")
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not imports, [n.lineno for n in imports]


def _mentions(node: ast.AST, package: str) -> bool:
    """An import of `ext_r2c.<package>`, absolute, `from ext_r2c import <package>`, or relative."""
    full = f"ext_r2c.{package}"
    if isinstance(node, ast.Import):
        return any(a.name == full or a.name.startswith(full + ".") for a in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level == 0:
            return (
                module == full
                or module.startswith(full + ".")
                or (module == "ext_r2c" and any(a.name == package for a in node.names))
            )
        return module.split(".")[0] == package or (not module and any(a.name == package for a in node.names))
    return False


def _mentions_a_bridge(node: ast.AST) -> bool:
    return _mentions(node, "bridges")


def test_no_other_module_imports_a_bridge() -> None:
    """Spec 006, FR-004 and constitution VIII: the core and the doors never import a bridge, and
    neither does `Remote` (spec 007, FR-035). The scans above already refuse any `ext_r2c` import
    beyond core; this names the rule."""
    bad: list[str] = []
    for package in ("core", "a2a", "mcp", "remote"):
        folder = files("ext_r2c") / package
        assert folder.is_dir(), f"ext_r2c/{package} is not in the installed wheel"
        for name, item in _sources(folder):
            for node in ast.walk(ast.parse(item.read_text(encoding="utf-8"), filename=name)):
                if _mentions_a_bridge(node):
                    bad.append(f"{package}/{name}:{node.lineno}")
    assert not bad, "a bridge is imported from:\n" + "\n".join(bad)


def test_the_mentions_check_sees_each_way_to_import_a_bridge() -> None:
    """The scan above is only worth its name if it recognises every spelling."""
    for source in (
        "import ext_r2c.bridges.langgraph",
        "from ext_r2c.bridges import langgraph",
        "from ext_r2c.bridges.langgraph import LangGraphAgent",
        "from ext_r2c import bridges",
        "from ..bridges import langgraph",
        "from .. import bridges",
    ):
        (node,) = ast.parse(source).body
        assert _mentions_a_bridge(node), source
    for source in ("import ext_r2c.core", "from ext_r2c.core import Driver", "from ext_r2c import core"):
        (node,) = ast.parse(source).body
        assert not _mentions_a_bridge(node), source


def test_langgraph_import_loads_no_door() -> None:
    """Spec 006, SC-010: the bridge needs neither the A2A nor the MCP packages."""
    code = (
        "import sys, ext_r2c.bridges.langgraph; "
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'a2a', 'mcp'}))"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_langgraph_import_without_the_extra_names_it() -> None:
    """With the extra's packages missing, the error says which extra to install."""
    for blocked in ("langgraph", "langchain_core"):
        code = (
            "import sys; "
            f"sys.modules[{blocked!r}] = None; "
            "\ntry:\n    import ext_r2c.bridges.langgraph\n"
            "except ImportError as exc:\n    print(exc)\n"
            "else:\n    print('imported')\n"
        )
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        assert 'ext-r2c[langgraph]' in out.stdout, (blocked, out.stdout, out.stderr)


# --- `ext_r2c.remote` (spec 007, research R13) ------------------------------------------------------

REMOTE_NAMES = ("Remote", "RemoteError", "A2AOptions", "MCPOptions")
# A module of `ext_r2c/remote/` imports the standard library, the core and its own modules where the
# import runs when the module is loaded. A door and the two SDKs come in only inside a function (or
# under `TYPE_CHECKING`, which never runs): that is how a door that is not exposed is never loaded.
REMOTE_ONLY_IN_FUNCTIONS = ("ext_r2c.a2a", "ext_r2c.mcp", "starlette", "a2a", "mcp")
REMOTE_NEVER = ("ext_r2c.bridges", "langgraph", "langchain", "langchain_core")


def _within(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _remote_imports(source: str, package: str = "ext_r2c.remote") -> list[tuple[int, str, bool]]:
    """(line, absolute name, runs when the module is loaded) for every import in the source of a
    module of `package`. A relative import is resolved; `from x import y` gives `x` and `x.y`, since
    `y` may be a module."""
    found: list[tuple[int, str, bool]] = []
    parts = package.split(".")

    def visit(node: ast.AST, at_load: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            at_load = False
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.body:
                visit(child, False)
            for child in node.orelse:
                visit(child, at_load)
            return
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, at_load) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = parts[: len(parts) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found.append((node.lineno, module, at_load))
            found.extend((node.lineno, f"{module}.{alias.name}", at_load) for alias in node.names)
        for child in ast.iter_child_nodes(node):
            visit(child, at_load)

    visit(ast.parse(source), True)
    return found


def _breaks_the_remote_rule(source: str) -> list[str]:
    bad: list[str] = []
    for line, name, at_load in _remote_imports(source):
        top = name.split(".")[0]
        if any(_within(name, never) for never in REMOTE_NEVER):
            bad.append(f"{line} {name} (a bridge, or a bridge's framework)")
        elif top == "ext_r2c":
            own = name == "ext_r2c" or _within(name, "ext_r2c.core") or _within(name, "ext_r2c.remote")
            door = _within(name, "ext_r2c.a2a") or _within(name, "ext_r2c.mcp")
            if not own and not (door and not at_load):
                bad.append(f"{line} {name} (a door is loaded inside a function only)" if door else f"{line} {name}")
        elif top in sys.stdlib_module_names:
            continue
        elif at_load or not any(_within(name, allowed) for allowed in REMOTE_ONLY_IN_FUNCTIONS):
            bad.append(f"{line} {name}" + (" (inside a function only)" if at_load else ""))
    return bad


def test_remote_imports_follow_the_rule() -> None:
    """Spec 007, FR-035: at load time the core and the standard library; a door inside a function;
    a bridge never."""
    folder = files("ext_r2c") / "remote"
    assert folder.is_dir(), "ext_r2c/remote is not in the installed wheel"
    bad = [
        f"remote/{name}:{problem}"
        for name, item in _sources(folder)
        for problem in _breaks_the_remote_rule(item.read_text(encoding="utf-8"))
    ]
    assert not bad, "ext_r2c/remote breaks its import rule:\n" + "\n".join(bad)


def test_the_remote_rule_sees_each_kind_of_bad_import() -> None:
    """The scan above is only worth its name if it refuses what it should and nothing more."""
    for source in (
        "import a2a",
        "import mcp.server",
        "import starlette.applications",
        "from ..a2a import a2a_app",
        "from .. import mcp",
        "from ext_r2c.mcp import R2CExtension",
        "from .. import URI",
        "import pydantic",
        "class Options:\n    from starlette.routing import Mount",
        "def build():\n    from ..bridges.langgraph import LangGraphAgent",
        "def build():\n    from .. import bridges",
        "def build():\n    import langgraph",
        "def build():\n    import yaml",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from langchain_core.tools import BaseTool",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n    import a2a",
    ):
        assert _breaks_the_remote_rule(source), source
    for source in (
        "import contextlib\nfrom collections.abc import Mapping",
        "from ..core import Limits, ToolSpec",
        "from ._errors import RemoteError",
        "from . import _compose",
        "def build():\n    from ..a2a import a2a_app\n    from starlette.routing import Mount",
        "async def build():\n    import mcp.server\n    from ..mcp import R2CExtension",
        "import typing\nif typing.TYPE_CHECKING:\n    from a2a.server.tasks import TaskStore",
    ):
        assert not _breaks_the_remote_rule(source), (source, _breaks_the_remote_rule(source))


def test_only_the_top_package_imports_remote() -> None:
    """The core, the doors and the bridges never import `Remote` (imports go one way)."""
    bad: list[str] = []
    for package in ("core", "a2a", "mcp", "bridges"):
        for name, item in _sources(files("ext_r2c") / package):
            for node in ast.walk(ast.parse(item.read_text(encoding="utf-8"), filename=name)):
                if _mentions(node, "remote"):
                    bad.append(f"{package}/{name}:{node.lineno}")
    assert not bad, "remote is imported from:\n" + "\n".join(bad)
    for source in ("import ext_r2c.remote", "from ext_r2c import remote", "from ..remote import Remote",
                   "from .. import remote", "from ext_r2c.remote._options import A2AOptions"):
        (node,) = ast.parse(source).body
        assert _mentions(node, "remote"), source


def _child(code: str) -> str:
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_importing_the_package_or_the_core_does_not_load_remote() -> None:
    assert _child("import sys, ext_r2c, ext_r2c.core; print('ext_r2c.remote' in sys.modules)") == "False"


def test_the_remote_names_are_exported_lazily_and_load_no_sdk() -> None:
    """Spec 007, FR-001: `from ext_r2c import Remote` works with no extra, and loads no door."""
    code = (
        "import sys, ext_r2c\n"
        "from ext_r2c import Remote, RemoteError, A2AOptions, MCPOptions\n"
        "heavy = {'a2a', 'mcp', 'mcp_types', 'starlette', 'yaml', 'langgraph', 'langchain', 'langchain_core'}\n"
        "print('ext_r2c.remote' in sys.modules, sorted({m.split('.')[0] for m in sys.modules} & heavy))\n"
        "print(Remote.__module__.startswith('ext_r2c.remote'), ext_r2c.Remote is Remote)\n"
    )
    assert _child(code).splitlines() == ["True []", "True True"]


def test_the_remote_names_are_public_and_an_unknown_name_is_an_attribute_error() -> None:
    import ext_r2c

    assert set(REMOTE_NAMES) <= set(ext_r2c.__all__)
    assert set(REMOTE_NAMES) <= set(dir(ext_r2c))
    assert {"URI", "MCP_KEY", "STANDARD_VERSION", "__version__"} <= set(ext_r2c.__all__), "the old names stay"
    with pytest.raises(AttributeError, match="no_such_name"):
        ext_r2c.no_such_name  # noqa: B018
