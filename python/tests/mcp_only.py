"""Run in a venv that holds the wheel with the `[mcp]` extra only (no dev group): the MCP door
works there and loads no other door or bridge (constitution VIII).

Not collected by pytest (no `test_` prefix). CI runs it as:
    python -I tests/mcp_only.py
It prints `mcp only: ok` or fails with an assertion.
"""

from __future__ import annotations

import importlib.util
import sys

OTHERS = ("a2a", "langchain", "langgraph")


class Hello:
    """A trivial source: one reply, then done."""

    pause = "live"

    def __init__(self) -> None:
        from ext_r2c.core import CardInfo

        self.card = CardInfo(name="hello", description="Says hello.", version="0.0.1")

    async def run(self, input, ctx):  # type: ignore[no-untyped-def]
        from ext_r2c.core import ReplyChunk

        yield ReplyChunk("Hello.", last=True)

    def resume(self, answer, ctx):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def main() -> None:
    import ext_r2c.mcp  # noqa: F401
    import ext_r2c.mcp.skills  # noqa: F401  (spec 005)
    import yaml  # noqa: F401  (what the `[mcp]` extra brings for the skills reader)

    assert importlib.util.find_spec("pytest") is None, "pytest is installed: this is not an mcp-only venv"
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"importing the MCP door loaded {loaded}"
    _server_check()
    _skills_check()
    print("mcp only: ok")


def _server_check() -> None:
    import anyio
    from ext_r2c import MCP_KEY
    from ext_r2c.core import tool_from_function
    from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    server = mcp_server("check", R2CExtension(tools=[tool_from_function(add), SourceTool(Hello())]))
    extensions = server._lowlevel_server.extensions  # what server/discover declares
    assert extensions == {MCP_KEY: {"revision": 1}}, extensions

    async def listed() -> list[str]:
        return sorted(t.name for t in await server.list_tools())

    names = anyio.run(listed)
    assert names == ["add", "agent"], names
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"building an MCP server loaded {loaded}"


def _skills_check() -> None:
    """Serve a skill from a folder, and read it back with the SDK's own in-memory `Client` (it carries
    the typed `skills/*` requests, research R13), here, where nothing but the `[mcp]` extra is installed."""
    import tempfile
    from pathlib import Path

    import anyio
    from ext_r2c import MCP_KEY
    from ext_r2c.core import tool_from_function
    from ext_r2c.mcp import R2CExtension, SkillsClient, SkillsExtension, mcp_server
    from mcp.client import Client
    from mcp.server.mcpserver import MCPServer

    EXTENSION_ID = "io.modelcontextprotocol/skills"  # the extension's own identifier, spelled out and not imported

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill = root / "hello"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: hello\ndescription: Says hello.\n---\nSay hello.\n", encoding="utf-8")
        (skill / "notes.txt").write_text("Some notes.\n", encoding="utf-8")

        extension = SkillsExtension(root)
        assert [s.name for s in extension.skills] == ["hello"], extension.skills
        assert extension.left_out == (), extension.left_out

        server = MCPServer("docs", extensions=[extension])
        assert server._lowlevel_server.extensions == {EXTENSION_ID: {"directoryRead": False}}

        async def round_trip() -> None:
            async with Client(server, cache=None) as client:
                skills = SkillsClient(client, origin="docs")
                assert skills.declared
                listing = await skills.list()
                assert not listing.refused and [i.name for i in listing.skills] == ["hello"], listing
                (item,) = listing.skills
                loaded = await skills.load(item)
                assert loaded.instructions.text().endswith("Say hello.\n"), loaded
                note = await skills.read(item, "skill://hello/notes.txt")
                assert note.text() == "Some notes.\n"

        anyio.run(round_trip)

        # Beside R2C: both are declared, R2C's first.
        both = mcp_server(
            "both", R2CExtension(tools=[tool_from_function(add)]), extensions=[SkillsExtension(root)]
        )
        assert list(both._lowlevel_server.extensions) == [MCP_KEY, EXTENSION_ID], both._lowlevel_server.extensions

    loaded_modules = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded_modules, f"serving skills loaded {loaded_modules}"


if __name__ == "__main__":
    main()
