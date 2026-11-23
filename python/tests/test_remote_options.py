"""The options of each door, and one door alone (spec 007, story 7; research R8 and R11).

Section 1 is the two option classes by themselves: they need no SDK. The later sections serve one
door alone, show that each option reaches its door, and check `middleware=` and the identity warning.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from collections.abc import Mapping

import pytest
from ext_r2c import A2AOptions, MCPOptions

# --- 1. The option classes ------------------------------------------------------------------------


def test_the_defaults_are_the_data_models() -> None:
    a2a, mcp = A2AOptions(), MCPOptions()
    assert (a2a.task_store, a2a.owner_resolver, a2a.path) == (None, None, "/")
    assert (mcp.path, mcp.security, mcp.owner, mcp.transport_security) == ("/mcp", None, None, None)
    assert isinstance(mcp.server, Mapping) and dict(mcp.server) == {}
    assert isinstance(mcp.http, Mapping) and dict(mcp.http) == {}
    assert [f.name for f in dataclasses.fields(A2AOptions)] == ["task_store", "owner_resolver", "path"]
    assert [f.name for f in dataclasses.fields(MCPOptions)] == [
        "path", "security", "owner", "transport_security", "server", "http",
    ]


@pytest.mark.parametrize("options", [A2AOptions, MCPOptions])
def test_the_options_are_keyword_only_and_frozen(options: type) -> None:
    with pytest.raises(TypeError):
        options("/rpc")
    built = options(path="/rpc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.path = "/other"


def test_the_mappings_cannot_be_mutated_and_do_not_follow_the_owners_dict() -> None:
    given = {"instructions": "Ask before you publish."}
    options = MCPOptions(server=given, http={"json_response": True})
    with pytest.raises(TypeError):
        options.server["title"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        MCPOptions().http["stateless_http"] = True  # type: ignore[index]
    given["title"] = "added later"
    assert dict(options.server) == {"instructions": "Ask before you publish."}
    assert dict(MCPOptions().server) == {} and dict(MCPOptions().http) == {}, "a default is never shared state"


@pytest.mark.parametrize("build", [
    lambda: A2AOptions(path=3),  # type: ignore[arg-type]
    lambda: MCPOptions(path=None),  # type: ignore[arg-type]
    lambda: MCPOptions(server=[("instructions", "x")]),  # type: ignore[arg-type]
    lambda: MCPOptions(http="json_response"),  # type: ignore[arg-type]
    lambda: MCPOptions(server={3: "x"}),  # type: ignore[dict-item]
    lambda: MCPOptions(owner="owner-1"),  # type: ignore[arg-type]
])
def test_a_field_of_the_wrong_type_is_a_type_error(build: object) -> None:
    with pytest.raises(TypeError):
        build()  # type: ignore[operator]


def test_the_options_need_no_sdk() -> None:
    """Both classes build with `a2a`, `mcp`, `starlette` and `yaml` blocked."""
    code = (
        "import sys\n"
        "for name in ('a2a', 'mcp', 'mcp_types', 'starlette', 'yaml'):\n"
        "    sys.modules[name] = None\n"
        "from ext_r2c import A2AOptions, MCPOptions\n"
        "print(A2AOptions(path='/rpc').path, MCPOptions(server={'instructions': 'x'}).path)\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "/rpc /mcp"
