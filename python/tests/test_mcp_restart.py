"""A restart between the question and the retry (spec 004, story 5, research R4, FR-018).

Fixed request-state keys keep a sealed state valid across a rebuilt server. A checkpoint source
on a durable store resumes from the stopping point; a live run lived in memory and is lost.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp_types as types
import pytest
from ext_r2c.core import ArtifactEvent, ArtifactMeta, Ask, ReplyChunk, UrlContent, Usage, UsageEvent
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp.source_tool import LOST
from mcp.server.request_state import RequestStateSecurity

from fake_sources import QUESTION
from mcp_harness import Scripted, accept, call, dump, mcp_client, run, serve, texts

ARGS = {"message": "Write the report", "context_id": "ctx-1"}
KEYS = [b"k" * 32]
USAGE = Usage(input_tokens=9)


def _steps() -> tuple[Any, ...]:
    csv = ArtifactEvent("f-1", ArtifactMeta(presentation="file"),
                        (UrlContent("https://files.example.com/r/a.csv", "text/csv"),))
    return (ReplyChunk("Before. "), csv, UsageEvent(USAGE), Ask(QUESTION), ReplyChunk("After.", last=True))


def _server(source: Scripted, **security: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=[SourceTool(source)]),
                      security=RequestStateSecurity(keys=KEYS, **security))


async def _pause(source: Scripted) -> str:
    async with serve(_server(source)) as served, mcp_client(served) as client:
        first = await call(client, "agent", ARGS)
    assert isinstance(first, types.InputRequiredResult) and first.request_state
    return first.request_state


def test_checkpoint_resumes_after_a_restart() -> None:
    store: dict[str, Any] = {}

    async def main() -> None:
        state = await _pause(Scripted("checkpoint", *_steps(), store=store))
        rebuilt = Scripted("checkpoint", *_steps(), store=store)
        async with serve(_server(rebuilt)) as served, mcp_client(served) as client:
            done = await call(client, "agent", ARGS, state=state, responses=accept("q-1", title="October"))
        assert not done.is_error
        assert [a.value for a in rebuilt.answers] == [{"title": "October"}]
        wire = dump(done)
        assert wire["content"][0]["text"] == "Before. After."
        assert wire["content"][1]["uri"] == "https://files.example.com/r/a.csv"

    run(main())


def test_live_run_is_lost_after_a_restart() -> None:
    async def main() -> None:
        state = await _pause(Scripted("live", *_steps()))
        rebuilt = Scripted("live", *_steps())
        async with serve(_server(rebuilt)) as served, mcp_client(served) as client:
            done = await call(client, "agent", ARGS, state=state, responses=accept("q-1", title="October"))
        assert done.is_error and texts(done) == [LOST]
        assert rebuilt.answers == []

    run(main())


@pytest.mark.parametrize("style", ["live", "checkpoint"])
def test_paused_run_ended_at_expiry(style: str) -> None:
    source = Scripted(style, Ask(QUESTION), ReplyChunk("Done.", last=True))

    async def main() -> None:
        tool = SourceTool(source)
        server = mcp_server("test", R2CExtension(tools=[tool]), security=RequestStateSecurity(keys=KEYS, ttl=0.2))
        async with serve(server) as served, mcp_client(served) as client:
            await call(client, "agent", ARGS)
            assert tool._open and tool._runs
            await asyncio.sleep(1.5)  # the state's TTL plus the door's second
            assert not tool._open and not tool._runs and not tool.driver._runs
        if style == "live":
            assert [a.outcome for a in source.answers] == ["declined"]
        else:
            assert source.answers == []  # a checkpoint source keeps its own checkpoint

    run(main())
