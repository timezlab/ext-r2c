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
    # phase 7 (T059): serve a skill from a folder and read it with the SDK's own client, here.


if __name__ == "__main__":
    main()
