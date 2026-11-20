"""Threads keyed by owner and context, and one unfinished call per context (spec 004, story 5,
research R5, R11, R2C-ID-1, R2C-ID-2)."""

from __future__ import annotations

import asyncio

import mcp_types as types
from ext_r2c.core import Ask, ReplyChunk, thread_id
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp.source_tool import BUSY
from mcp.server.request_state import RequestStateSecurity

from fake_sources import QUESTION
from mcp_harness import Scripted, accept, auth, call, mcp_client, principal, run, serve, texts

ARGS = {"message": "Write the report", "context_id": "ctx-1"}


def _asking() -> Scripted:
    return Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))


def test_owners_never_share_a_thread() -> None:
    source = Scripted("live", ReplyChunk("Hi.", last=True))

    async def main() -> None:
        server = mcp_server("test", R2CExtension(tools=[SourceTool(source)]), **auth())
        async with serve(server) as served:
            async with mcp_client(served, user="alice") as alice, mcp_client(served, user="bob") as bob:
                await call(alice, "agent", ARGS)
                await call(bob, "agent", ARGS)
        assert source.threads == [thread_id("mcp", principal("alice"), "ctx-1"),
                                  thread_id("mcp", principal("bob"), "ctx-1")]
        assert source.threads[0] != source.threads[1]

    run(main())


def test_chosen_context_is_returned_and_reused() -> None:
    source = Scripted("live", ReplyChunk("Hi.", last=True))

    async def main() -> None:
        async with serve(mcp_server("test", R2CExtension(tools=[SourceTool(source)]))) as served:
            async with mcp_client(served) as client:
                first = await call(client, "agent", {"message": "Hello"})
                chosen = first.structured_content["context_id"]
                second = await call(client, "agent", {"message": "Again", "context_id": chosen})
        assert isinstance(chosen, str) and len(chosen) == 32
        assert second.structured_content == {"context_id": chosen}
        assert source.threads == [thread_id("mcp", "anonymous", chosen)] * 2

    run(main())


def test_owner_override() -> None:
    source = Scripted("live", ReplyChunk("Hi.", last=True))

    async def main() -> None:
        extension = R2CExtension(tools=[SourceTool(source)], owner=lambda ctx: "team-1")
        async with serve(mcp_server("test", extension)) as served, mcp_client(served) as client:
            await call(client, "agent", ARGS)
        assert source.threads == [thread_id("mcp", "team-1", "ctx-1")]

    run(main())


def test_busy_context() -> None:
    source = _asking()

    async def main() -> None:
        server = mcp_server("test", R2CExtension(tools=[SourceTool(source)]), **auth())
        async with serve(server) as served:
            async with mcp_client(served, user="alice") as alice, mcp_client(served, user="bob") as bob:
                paused = await call(alice, "agent", ARGS)
                assert isinstance(paused, types.InputRequiredResult)
                busy = await call(alice, "agent", {**ARGS, "message": "Something else"})
                assert busy.is_error and texts(busy) == [BUSY]
                other = await call(bob, "agent", ARGS)
                assert isinstance(other, types.InputRequiredResult)
                done = await call(alice, "agent", ARGS, state=paused.request_state, responses=accept("q-1", title="T"))
                assert not done.is_error and texts(done) == ["Done."]
                again = await call(alice, "agent", ARGS)
                assert isinstance(again, types.InputRequiredResult)

    run(main())


def test_context_free_once_the_state_expired() -> None:
    source = _asking()

    async def main() -> None:
        security = RequestStateSecurity(keys=[b"k" * 32], ttl=0.3)
        server = mcp_server("test", R2CExtension(tools=[SourceTool(source)]), security=security)
        async with serve(server) as served, mcp_client(served) as client:
            await call(client, "agent", ARGS)
            busy = await call(client, "agent", ARGS)
            assert busy.is_error
            await asyncio.sleep(0.4)
            free = await call(client, "agent", ARGS)
        assert isinstance(free, types.InputRequiredResult)
        assert [a.outcome for a in source.answers] == ["declined"]  # the expired run ended

    run(main())
