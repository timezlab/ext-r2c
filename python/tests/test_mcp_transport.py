"""The streaming test transport (research R15): progress reaches the client while the tool still
runs, and the recording sees both directions."""

from __future__ import annotations

import asyncio

import httpx2
import mcp_types as types
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context, MCPServer
from mcp_harness import BASE, URL, mcp_client, run, serve


def _server() -> tuple[MCPServer, asyncio.Event]:
    server = MCPServer("transport-check")
    seen = asyncio.Event()

    @server.tool()
    async def slow(ctx: Context) -> str:
        """Reports progress, then waits until the client has seen it."""
        await ctx.report_progress(1, message="working")
        try:
            await asyncio.wait_for(seen.wait(), 2.0)
        except TimeoutError:
            return "the progress never arrived"
        return "the progress arrived first"

    return server, seen


def _handler(seen: asyncio.Event):  # type: ignore[no-untyped-def]
    async def handle(message: object) -> None:
        if isinstance(message, types.ProgressNotification):
            seen.set()

    return handle


async def _call(client: Client) -> str:
    result = await client.session.call_tool("slow", {}, meta={"progressToken": "p-1"})
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    return block.text


def test_transport_streams_progress_before_result() -> None:
    async def main() -> None:
        server, seen = _server()
        record: list[tuple[str, dict]] = []
        async with serve(server, record=record) as served:
            async with mcp_client(served, active=False, form=False, message_handler=_handler(seen)) as client:
                assert await _call(client) == "the progress arrived first"
        methods = [(side, m.get("method") or "result") for side, m in record if m.get("method") != "server/discover"]
        assert ("remote", "notifications/progress") in methods
        assert methods.index(("remote", "notifications/progress")) < len(methods) - 1

    run(main())


def test_buffering_transport_holds_progress_back() -> None:
    """Why the test transport exists: `httpx2.ASGITransport` hands over the body only once the
    app has finished, so the progress reaches the client after the tool gave up waiting."""

    async def main() -> None:
        server, seen = _server()
        async with serve(server) as served:
            http = httpx2.AsyncClient(transport=httpx2.ASGITransport(served.app), base_url=BASE)
            client = Client(streamable_http_client(URL, http_client=http), message_handler=_handler(seen), cache=None)
            async with client:
                assert await _call(client) == "the progress never arrived"

    run(main())
