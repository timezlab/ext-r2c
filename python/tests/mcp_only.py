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
    _remote_check()
    print("mcp only: ok")


def _remote_check() -> None:
    """An MCP-only `Remote` serves its endpoint with nothing of A2A loaded, and the A2A door names its
    extra (spec 007, SC-010)."""
    import asyncio

    from ext_r2c import MCPOptions, Remote
    from mcp.server.request_state import RequestStateSecurity

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    source = Hello()
    remote = Remote(expose=["mcp"], agent=source, mcp_tool=True, tools=[add], approve=["add"],
                    mcp=MCPOptions(security=RequestStateSecurity(keys=[b"k" * 32])))
    app = remote.app()

    async def asked() -> tuple[int, int, int]:
        async with app.router.lifespan_context(app):
            return (await _ask(app, "POST", "/mcp", b"{}"), await _ask(app, "GET", "/.well-known/agent-card.json"),
                    await _ask(app, "POST", "/", b"{}"))

    mcp_status, card_status, rpc_status = asyncio.run(asked())
    assert mcp_status not in (404, 421), f"the MCP endpoint answered {mcp_status}"
    assert (card_status, rpc_status) == (404, 404), f"an MCP-only Remote answered A2A paths: {card_status}, {rpc_status}"
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"an MCP-only Remote loaded {loaded}"

    try:
        Remote(expose=["a2a"], agent=source, url="https://remote.example.com")
    except ImportError as error:
        assert "ext-r2c[a2a]" in str(error), str(error)
    else:
        raise AssertionError("the A2A door built without the [a2a] extra")


async def _ask(app, method: str, path: str, body: bytes = b"") -> int:  # type: ignore[no-untyped-def]
    """One HTTP request to an ASGI app with no client library: the status."""
    waiting = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[dict] = []  # type: ignore[type-arg]

    async def receive():  # type: ignore[no-untyped-def]
        return waiting.pop() if waiting else {"type": "http.disconnect"}

    async def send(message) -> None:  # type: ignore[no-untyped-def]
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8000"), (b"content-type", b"application/json")],
        "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 50000),
    }
    await app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


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
        assert server._lowlevel_server.extensions == {EXTENSION_ID: {"directoryRead": True}}

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
