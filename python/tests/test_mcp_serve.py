"""A source served as an MCP tool, with R2C active (spec 004, story 1).

Both fakes of spec 002 run the same script, so every flow runs for both pause styles, and their
wires must be the same (SC-002). Each round is driven by hand through a raw MCP SDK session.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    ArtifactEvent,
    ArtifactMeta,
    Ask,
    ReplyChunk,
    TextContent,
    UrlContent,
    Usage,
    UsageEvent,
    answer_from_mcp,
    mcp_form,
    parse,
    to_json,
)
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp._codec import message

from fake_sources import APPROVAL, QUESTION, CheckpointFake, LiveFake
from mcp_harness import Hang, Progress, Raise, Scripted, accept, call, dump, mcp_client, normalise, refuse, run, serve, texts

STYLES = ["checkpoint", "live"]
ARGS = {"message": "Write the report", "context_id": "ctx-1"}
PUBLISH = {"message": "Write the report and publish it", "context_id": "ctx-1"}
EXAMPLES = Path(__file__).resolve().parents[2] / "standard" / "v1" / "examples" / "mcp"


def _fake(style: str) -> Any:
    return CheckpointFake({}) if style == "checkpoint" else LiveFake()


def _server(*tools: Any, **kwargs: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=list(tools)), **kwargs)


def _question(id: str, title: str) -> Any:
    return parse({"kind": "question", "id": id, "title": title, "answer_by": {"role": "person"},
                  "fields": [{"key": "name", "header": "Name", "text": title, "type": "text"}]})


def _step(id: str, state: str = "running", type: str = "step") -> ActivityEvent:
    return ActivityEvent(Activity.parse({"kind": "activity", "id": id, "type": type, "label": f"Label {id}",
                                         "state": state}))


@pytest.mark.parametrize("style", STYLES)
def test_question_round_trip(style: str) -> None:
    source = _fake(style)

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert isinstance(first, types.InputRequiredResult)
            wire = dump(first)
            assert list(wire["inputRequests"]) == ["q-1"]
            params = wire["inputRequests"]["q-1"]["params"]
            assert params["mode"] == "form"
            assert params["requestedSchema"] == mcp_form(QUESTION).requested_schema
            assert params["message"] == message(QUESTION)
            assert wire["_meta"][MCP_KEY] == {"input_requests": {"q-1": to_json(QUESTION)}}
            done = await call(client, "agent", ARGS, state=first.request_state,
                              responses=accept("q-1", title="October stock"))
        assert isinstance(done, types.CallToolResult) and not done.is_error
        assert source.answers == [answer_from_mcp(QUESTION, "accept", {"title": "October stock"})]
        assert source.answers[0].answered_by.role == "person"
        assert texts(done) == ["Got: October stock"]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_other_value_merged(style: str) -> None:
    example = json.loads((EXAMPLES / "elicitation-question-other.json").read_text("utf-8"))
    asked = example["steps"][0]["body"]["result"]
    question = parse(asked["_meta"][MCP_KEY]["input_requests"]["q-1"])
    content = example["steps"][1]["body"]["params"]["inputResponses"]["q-1"]["content"]
    source = Scripted(style, Ask(question), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert dump(first)["inputRequests"]["q-1"]["params"]["requestedSchema"] == \
                asked["inputRequests"]["q-1"]["params"]["requestedSchema"]
            await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", **content))
        assert [a.value for a in source.answers] == [{"warehouse": "East annex"}]

    run(main())


@pytest.mark.parametrize("action", ["decline", "cancel"])
@pytest.mark.parametrize("style", STYLES)
def test_decline_and_cancel_give_declined(style: str, action: str) -> None:
    source = _fake(style)

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            done = await call(client, "agent", ARGS, state=first.request_state, responses=refuse("q-1", action))
        assert [a.outcome for a in source.answers] == ["declined"]
        assert source.answers[0].answered_by.role == "person"
        assert isinstance(done, types.CallToolResult) and texts(done) == ["Declined"]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_approval_denied_with_reason(style: str) -> None:
    source = _fake(style)

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", PUBLISH)
            wire = dump(first)
            assert wire["inputRequests"]["ap-1"]["params"]["requestedSchema"] == mcp_form(APPROVAL).requested_schema
            assert wire["_meta"][MCP_KEY]["input_requests"]["ap-1"] == to_json(APPROVAL)
            done = await call(client, "agent", PUBLISH, state=first.request_state,
                              responses=accept("ap-1", decision="deny", reason="Not before Monday."))
        assert [a.value for a in source.answers] == [{"decision": "deny", "reason": "Not before Monday."}]
        assert texts(done) == ["Not done: Not before Monday."]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_two_questions_one_after_the_other(style: str) -> None:
    q1, q2 = _question("q-1", "First?"), _question("q-2", "Second?")
    u1, u2 = Usage(input_tokens=10), Usage(input_tokens=20, output_tokens=4)
    source = Scripted(style, Ask(q1), UsageEvent(u1), Ask(q2), UsageEvent(u2), ReplyChunk("Both.", last=True))

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert list(first.input_requests) == ["q-1"]
            assert dump(first)["_meta"][MCP_KEY] == {"input_requests": {"q-1": to_json(q1)}}
            second = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", name="A"))
            assert isinstance(second, types.InputRequiredResult)
            assert list(second.input_requests) == ["q-2"]
            assert dump(second)["_meta"][MCP_KEY] == {"input_requests": {"q-2": to_json(q2)}, "usage": to_json(u1)}
            done = await call(client, "agent", ARGS, state=second.request_state, responses=accept("q-2", name="B"))
        assert [a.value for a in source.answers] == [{"name": "A"}, {"name": "B"}]
        assert dump(done)["_meta"][MCP_KEY] == to_json(u2)

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_final_result(style: str) -> None:
    usage = Usage(input_tokens=5200, output_tokens=940)
    source = Scripted(
        style,
        ReplyChunk("Before the ask. "),
        ArtifactEvent("f-1", ArtifactMeta(presentation="file"),
                      (UrlContent("https://files.example.com/r/inventory.csv", "text/csv"),)),
        Ask(QUESTION),
        ArtifactEvent("t-1", ArtifactMeta(presentation="inline"), (TextContent("A-113 12"),)),
        ReplyChunk("After.", last=True),
        UsageEvent(usage),
    )

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            done = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="T"))
        wire = dump(done)
        assert wire["content"] == [
            {"type": "text", "text": "Before the ask. After.",
             "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "inline", "response": True}}},
            {"type": "resource_link", "uri": "https://files.example.com/r/inventory.csv", "name": "inventory.csv",
             "mimeType": "text/csv", "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "file"}}},
            {"type": "text", "text": "A-113 12", "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "inline"}}},
        ]
        assert wire["_meta"][MCP_KEY] == to_json(usage)
        assert wire["structuredContent"] == {"context_id": "ctx-1"}

    run(main())


def test_same_wire_for_both_pause_styles() -> None:
    async def flow(style: str) -> list[Any]:
        record: list[Any] = []
        async with serve(_server(SourceTool(_fake(style))), record=record) as served:
            async with mcp_client(served) as client:
                first = await call(client, "agent", ARGS, token="p-1")
                await call(client, "agent", ARGS, state=first.request_state, token="p-2",
                           responses=accept("q-1", title="October stock"))
        return normalise(record)

    async def main() -> None:
        checkpoint, live = await flow("checkpoint"), await flow("live")
        assert checkpoint == live
        assert any(m.get("method") == "notifications/progress" for side, m in live if side == "remote")

    run(main())


def test_cancel() -> None:
    source = Scripted("live", _step("s-1"), Hang())

    async def main() -> None:
        progress = Progress()
        async with serve(_server(SourceTool(source))) as served:
            async with mcp_client(served, message_handler=progress) as client:
                task = asyncio.create_task(call(client, "agent", ARGS, token="p-1"))
                await source.hanging.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            for _ in range(200):
                if source.saw_cancelled is not None:
                    break
                await asyncio.sleep(0.01)
        assert source.saw_cancelled is True

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_source_error(style: str) -> None:
    usage = Usage(input_tokens=7)
    source = Scripted(style, UsageEvent(usage), ReplyChunk("Partial. "), Raise("the agent broke"))

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            done = await call(client, "agent", ARGS)
        assert isinstance(done, types.CallToolResult) and done.is_error
        assert any("the agent broke" in t for t in texts(done))
        assert dump(done)["_meta"][MCP_KEY] == to_json(usage)

    run(main())


def test_progress_only_with_token() -> None:
    def source() -> Scripted:
        return Scripted("live", _step("s-1"), _step("s-1", "done"), ReplyChunk("Done.", last=True))

    async def main() -> None:
        with_token, without = Progress(), Progress()
        async with serve(_server(SourceTool(source()))) as served:
            async with mcp_client(served, message_handler=with_token) as client:
                await call(client, "agent", ARGS, token="p-1")
        async with serve(_server(SourceTool(source()))) as served:
            async with mcp_client(served, message_handler=without) as client:
                await call(client, "agent", ARGS)
        assert [(p["progressToken"], p["progress"], p["message"]) for p in with_token.seen] == \
            [("p-1", 1, "Label s-1"), ("p-1", 2, "Label s-1")]
        assert [p["_meta"][MCP_KEY]["state"] for p in with_token.seen] == ["running", "done"]
        assert without.seen == []

    run(main())
