"""Activation over MCP (spec 004, story 4): R2C `_meta` only for a round whose client
capabilities list the key; the same elicitation either way; `declined` without form support."""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import Activity, ActivityEvent, ReplyChunk, answer_from_mcp, mcp_form
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp._codec import message

from fake_sources import QUESTION, CheckpointFake, LiveFake
from mcp_harness import Progress, Scripted, accept, call, dump, mcp_client, run, serve, texts

STYLES = ["checkpoint", "live"]
ARGS = {"message": "Write the report", "context_id": "ctx-1"}


def _fake(style: str) -> Any:
    return CheckpointFake({}) if style == "checkpoint" else LiveFake()


def _server(source: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=[SourceTool(source)]))


def _activity(id: str, type: str) -> ActivityEvent:
    return ActivityEvent(Activity.parse({"kind": "activity", "id": id, "type": type, "label": f"Label {id}",
                                         "state": "running"}))


def test_discover_declares_the_key() -> None:
    async def main() -> None:
        async with serve(_server(LiveFake())) as served, mcp_client(served) as client:
            assert client.server_capabilities.extensions[MCP_KEY] == {"revision": 1}

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_active_round_carries_meta(style: str) -> None:
    async def main() -> None:
        progress = Progress()
        async with serve(_server(_fake(style))) as served, mcp_client(served, message_handler=progress) as client:
            first = await call(client, "agent", ARGS, token="p-1")
            done = await call(client, "agent", ARGS, state=first.request_state, token="p-2",
                              responses=accept("q-1", title="T"))
        assert MCP_KEY in dump(first)["_meta"]
        assert all(MCP_KEY in p["_meta"] for p in progress.seen) and len(progress.seen) == 2
        assert MCP_KEY in dump(done)["_meta"] and MCP_KEY in dump(done)["content"][0]["_meta"]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_not_active(style: str) -> None:
    source = _fake(style)

    async def main() -> None:
        record: list[Any] = []
        progress = Progress()
        async with serve(_server(source), record=record) as served:
            async with mcp_client(served, active=False, message_handler=progress) as client:
                first = await call(client, "agent", ARGS, token="p-1")
                params = dump(first)["inputRequests"]["q-1"]["params"]
                assert params["message"] == message(QUESTION)
                assert params["requestedSchema"] == mcp_form(QUESTION).requested_schema
                done = await call(client, "agent", ARGS, state=first.request_state, token="p-2",
                                  responses=accept("q-1", title="October stock"))
        assert source.answers == [answer_from_mcp(QUESTION, "accept", {"title": "October stock"})]
        assert isinstance(done, types.CallToolResult) and texts(done) == ["Got: October stock"]
        assert len(progress.seen) == 2
        calls = {m["id"] for side, m in record if side == "client" and m.get("method") == "tools/call"}
        remote = [m for side, m in record if side == "remote" and (m.get("id") in calls or "method" in m)]
        assert len(remote) == 4  # two progress notifications, two results
        assert MCP_KEY not in json.dumps(remote)

    run(main())


def test_no_reasoning_without_activation() -> None:
    def source() -> Scripted:
        return Scripted("live", _activity("r-1", "reasoning"), _activity("s-1", "step"), ReplyChunk("Done.", last=True))

    async def main() -> None:
        active, plain = Progress(), Progress()
        async with serve(_server(source())) as served, mcp_client(served, message_handler=active) as client:
            await call(client, "agent", ARGS, token="p-1")
        async with serve(_server(source())) as served:
            async with mcp_client(served, active=False, message_handler=plain) as client:
                await call(client, "agent", ARGS, token="p-1")
        assert [p["message"] for p in active.seen] == ["Label r-1", "Label s-1"]
        assert [(p["progress"], p["message"]) for p in plain.seen] == [(1, "Label s-1")]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_no_form_support(style: str) -> None:
    source = _fake(style)

    async def main() -> None:
        async with serve(_server(source)) as served, mcp_client(served, form=False) as client:
            done = await call(client, "agent", ARGS)
        assert isinstance(done, types.CallToolResult) and not done.is_error
        assert [a.outcome for a in source.answers] == ["declined"]
        assert texts(done) == ["Declined"]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_activation_per_round(style: str) -> None:
    async def main() -> None:
        async with serve(_server(_fake(style))) as served:
            async with mcp_client(served) as active:
                first = await call(active, "agent", ARGS)
            assert MCP_KEY in dump(first)["_meta"]
            async with mcp_client(served, active=False) as plain:
                done = await call(plain, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="T"))
        assert MCP_KEY not in json.dumps(dump(done))
        assert texts(done) == ["Got: T"]

    run(main())
