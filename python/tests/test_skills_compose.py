"""Skills beside R2C, alone, and on a server built by hand (spec 005, story 5, SC-006).

`SkillsExtension` is an MCP extension of its own, not part of R2C (research R1): a server may carry it
with R2C (`mcp_server(..., extensions=[skills])`), without R2C, or beside tools it knows nothing of. R2C
over MCP behaves as spec 004 says whether or not skills are there, and so do the skills.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import tool_from_function
from ext_r2c.mcp import R2CExtension, SkillsClient, SkillsExtension, SourceTool, mcp_server
from fake_sources import CheckpointFake, LiveFake
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_harness import accept, call, mcp_client, normalise, run, serve, texts
from mcp_transport import Record
from skills_fixtures import standard_tree

SKILLS_ID = "io.modelcontextprotocol/skills"  # the extension's own identifier, spelled out and not imported
STYLES = ["checkpoint", "live"]
ARGS ={"message": "Write the report", "context_id": "ctx-1"}


def _fake(style: str) -> Any:
    return CheckpointFake({}) if style == "checkpoint" else LiveFake()


def _with_skills(style: str, root: Path) -> MCPServer:
    return mcp_server("test", R2CExtension(tools=[SourceTool(_fake(style))]), extensions=[SkillsExtension(root)])


def _without_skills(style: str) -> MCPServer:
    return mcp_server("test", R2CExtension(tools=[SourceTool(_fake(style))]))


async def question_flow(client: Client, between: Callable[[Client], Awaitable[None]] | None = None) -> None:
    """The simplest flow of spec 004 that asks a question: ask, wait for the answer, finish.
    `between` runs while the call is paused."""
    first = await call(client, "agent", ARGS)
    assert isinstance(first, types.InputRequiredResult)
    if between is not None:
        await between(client)
    done = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="October stock"))
    assert isinstance(done, types.CallToolResult) and not done.is_error
    assert texts(done) == ["Got: October stock"]


async def read_every_skill(client: Client, expected: dict[str, bytes]) -> None:
    """The skills flows: list, then read every file of every skill through the verifying client."""
    skills = SkillsClient(client, origin="docs")
    assert skills.declared
    listing = await skills.list()
    assert not listing.refused
    got: dict[str, bytes] = {}
    for item in listing.skills:
        loaded = await skills.load(item)
        assert loaded.instructions.uri == item.uri
        for ref in item.files:
            got[ref.uri] = (await skills.read(item, ref.uri)).data
    assert got == expected


def tool_calls(record: Record) -> Record:
    """What crossed for `tools/call` and nothing else: the requests, the responses to them, and the
    notifications the remote sent meanwhile."""
    ids = {m["id"] for side, m in record if side == "client" and m.get("method") == "tools/call" and "id" in m}
    return [
        (side, message)
        for side, message in record
        if (side == "client" and message.get("method") == "tools/call")
        or (side == "remote" and (message.get("id") in ids or str(message.get("method", "")).startswith("notifications/")))
    ]


class TestBesideR2C:
    @pytest.mark.parametrize("style", STYLES)
    def test_an_r2c_flow_and_the_skills_flows_complete_on_one_server(self, tmp_path: Path, style: str) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()

        async def body() -> dict[str, Any]:
            async with serve(_with_skills(style, tree.root)) as served, mcp_client(served) as client:
                await question_flow(client)
                await read_every_skill(client, expected)
                assert client.server_capabilities.extensions is not None
                return dict(client.server_capabilities.extensions)

        declared = run(body())
        assert set(declared) == {MCP_KEY, SKILLS_ID}  # `server/discover` declares both
        assert declared[MCP_KEY] == {"revision": 1}
        assert set(declared[SKILLS_ID]) == {"directoryRead"}  # each says its own settings and not the other's

    @pytest.mark.parametrize("style", STYLES)
    def test_a_paused_r2c_call_is_not_disturbed_by_skills_requests_in_the_middle(self, tmp_path: Path, style: str) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()

        async def between(client: Client) -> None:
            await read_every_skill(client, expected)

        async def body() -> None:
            async with serve(_with_skills(style, tree.root)) as served, mcp_client(served) as client:
                await question_flow(client, between)

        run(body())

    @pytest.mark.parametrize("style", STYLES)
    def test_the_r2c_wire_is_the_same_with_skills_on_the_server_and_without(self, tmp_path: Path, style: str) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()

        async def wire(server: MCPServer, *, skills: bool) -> Record:
            record: Record = []
            async with serve(server, record=record) as served, mcp_client(served) as client:
                await question_flow(client, (lambda c: read_every_skill(c, expected)) if skills else None)
            return record

        with_skills = run(wire(_with_skills(style, tree.root), skills=True))
        without = run(wire(_without_skills(style), skills=False))
        crossed = tool_calls(with_skills)
        assert len(crossed) >= 4  # two requests and their two responses, at least
        assert normalise(crossed) == normalise(tool_calls(without))
        # And the skills did cross the same wire: this is not a comparison of two servers without them.
        methods = {m.get("method") for side, m in with_skills if side == "client"}
        assert {"skills/list", "resources/read"} <= methods


    def test_the_tool_list_is_the_same_with_skills_on_the_server_and_without(self, tmp_path: Path) -> None:
        """R2C lists each tool with its own input schema, through a middleware of its own; it still
        does when the server carries more extensions."""
        root = standard_tree(tmp_path).root

        def build(*extensions: Any) -> MCPServer:
            def add(a: int, b: int) -> int:
                """Add two numbers."""
                return a + b

            tools = [tool_from_function(add), SourceTool(LiveFake())]
            return mcp_server("test", R2CExtension(tools=tools), extensions=list(extensions))

        async def listed(server: MCPServer) -> list[dict[str, Any]]:
            async with serve(server) as served, mcp_client(served) as client:
                return [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in (await client.list_tools()).tools]

        with_skills = run(listed(build(SkillsExtension(root))))
        without = run(listed(build()))
        assert [t["name"] for t in with_skills] == ["add", "agent"]
        assert with_skills == without


class TestAlone:
    def test_a_skills_only_server_serves_skills_declares_no_r2c_and_lists_no_tool(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()

        async def body() -> tuple[dict[str, Any], list[Any]]:
            server = MCPServer("docs", extensions=[SkillsExtension(tree.root)])
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                await read_every_skill(client, expected)
                assert client.server_capabilities.extensions is not None
                return dict(client.server_capabilities.extensions), list((await client.list_tools()).tools)

        declared, tools = run(body())
        assert set(declared) == {SKILLS_ID}  # R2C is not declared
        assert set(declared[SKILLS_ID]) == {"directoryRead"}
        assert tools == []

    def test_a_server_built_by_hand_keeps_its_own_tool_and_gains_the_skills(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()
        server = MCPServer("hand", extensions=[SkillsExtension(tree.root)])

        @server.tool()
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        async def body() -> tuple[list[str], list[str]]:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                await read_every_skill(client, expected)
                done = await client.call_tool("add", {"a": 2, "b": 3})
                assert not done.is_error
                return [t.name for t in (await client.list_tools()).tools], texts(done)

        names, answer = run(body())
        assert names == ["add"] and answer == ["5"]  # the extension does not touch `tools/list` or `tools/call`

    def test_the_same_tool_gives_the_same_wire_with_the_extension_and_without_it(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)

        def build(*extensions: Any) -> MCPServer:
            server = MCPServer("hand", extensions=list(extensions))

            @server.tool()
            def add(a: int, b: int) -> int:
                """Add two numbers."""
                return a + b

            return server

        async def wire(server: MCPServer) -> Record:
            record: Record = []
            async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
                await client.call_tool("add", {"a": 2, "b": 3})
            return record

        with_it = run(wire(build(SkillsExtension(tree.root))))
        without = run(wire(build()))
        assert normalise(tool_calls(with_it)) == normalise(tool_calls(without))


class TestTheComposer:
    def test_without_extensions_the_server_is_what_it_was(self) -> None:
        server = _without_skills("live")
        assert list(server._lowlevel_server.extensions) == [MCP_KEY]

    @pytest.mark.parametrize("how", [list, tuple], ids=["a list", "a tuple"])
    def test_extensions_follow_r2c_in_the_order_given(self, tmp_path: Path, how: Callable[..., Any]) -> None:
        root = standard_tree(tmp_path).root
        server = mcp_server("test", R2CExtension(tools=[SourceTool(LiveFake())]), extensions=how([SkillsExtension(root)]))
        assert list(server._lowlevel_server.extensions) == [MCP_KEY, SKILLS_ID]

    def test_two_extensions_with_one_identifier_fail_as_the_sdk_says_and_leave_r2c_free(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        r2c = R2CExtension(tools=[SourceTool(LiveFake())])
        with pytest.raises(ValueError, match="already registered"):
            mcp_server("test", r2c, extensions=[SkillsExtension(root), SkillsExtension(root)])
        assert r2c.ttl is None  # not left half served: it can be used again
        mcp_server("test", r2c, extensions=[SkillsExtension(root)])

    def test_r2c_given_again_as_an_extension_is_refused_by_the_sdk(self) -> None:
        r2c = R2CExtension(tools=[SourceTool(LiveFake())])
        with pytest.raises(ValueError, match="already registered"):
            mcp_server("test", r2c, extensions=[r2c])
        assert r2c.ttl is None
