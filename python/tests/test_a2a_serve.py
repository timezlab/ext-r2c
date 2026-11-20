"""A source served over A2A, with R2C active (spec 003, story 1).

Both fakes of spec 002 run the same script, so every flow runs for both pause styles, and
their wires must be the same (SC-002).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types.a2a_pb2 import CancelTaskRequest, StreamResponse, TaskState
from ext_r2c import URI
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.a2a._codec import read_artifact, read_part
from ext_r2c.core import (
    Activity,
    Answer,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    BytesContent,
    Limits,
    Question,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    TextContent,
    Usage,
)

from a2a_harness import Caller, a2a_client, answer, ids, kinds, run, send, serve, wire
from fake_sources import APPROVAL, CARD, QUESTION, CheckpointFake, LiveFake

STYLES = ["checkpoint", "live"]


def _source(style: str) -> Any:
    return CheckpointFake({}) if style == "checkpoint" else LiveFake()


def _card() -> Any:
    return agent_card(CARD, "https://remote.example.com/")


def _status_objects(event: StreamResponse) -> list[Any]:
    """The R2C objects of a status update, in Part order."""
    parts = event.status_update.status.message.parts
    return [o for o in (read_part(p) for p in parts) if o is not None]


def _has_text(event: StreamResponse) -> bool:
    return any(p.HasField("text") and p.text for p in event.status_update.status.message.parts)


def _reply(events: list[StreamResponse]) -> str:
    """The reply text gathered from the `reply` artifact chunks."""
    out = []
    for e in events:
        if e.HasField("artifact_update") and e.artifact_update.artifact.artifact_id == "reply":
            meta, contents = read_artifact(e.artifact_update.artifact)
            assert meta == ArtifactMeta(presentation="inline", response=True)
            out.extend(c.text for c in contents if isinstance(c, TextContent))
    return "".join(out)


def _person(request: Question | Approval, **value: Any) -> Answer:
    return Answer(id=request.id, outcome="answered", answered_by={"role": "person"}, value=value)


async def _paused(tc: Caller, text: str) -> list[StreamResponse]:
    first = await send(tc, text)
    assert kinds(first) == ["task", "working", "input_required"]
    return first


@pytest.mark.parametrize("style", STYLES)
def test_question_then_reply(style: str) -> None:
    async def go() -> None:
        source = _source(style)
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write the report")
            working, asked = first[1], first[2]
            (activity,) = _status_objects(working)
            assert isinstance(activity, Activity) and activity.state == "running"
            assert _has_text(working)  # R2C-CORE-4
            assert _status_objects(asked) == [QUESTION]  # R2C-A2A-1
            assert _has_text(asked)

            reply = _person(QUESTION, title="October")
            second = await answer(tc, first, reply, QUESTION)
            assert kinds(second) == ["artifact:reply", "working", "completed"]
            assert _reply(second) == "Got: October"
            assert not second[0].artifact_update.append
            assert _status_objects(second[-1]) == [Usage(output_tokens=3)]  # R2C-A2A-4
            assert source.answers == [reply]

    run(go())


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize(("value", "said"), [
    ({"decision": "allow"}, "Done"),
    ({"decision": "deny", "reason": "Not this week."}, "Not done: Not this week."),
])
def test_approval(style: str, value: dict[str, Any], said: str) -> None:
    async def go() -> None:
        source = _source(style)
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write and publish the report")
            assert _status_objects(first[2]) == [APPROVAL]
            reply = _person(APPROVAL, **value)
            second = await answer(tc, first, reply, APPROVAL)
            assert kinds(second)[-1] == "completed"
            assert _reply(second) == said
            assert source.answers == [reply]

    run(go())


@pytest.mark.parametrize("style", STYLES)
def test_declined(style: str) -> None:
    async def go() -> None:
        source = _source(style)
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write the report")
            reply = Answer(id="q-1", outcome="declined", answered_by={"role": "person"})
            second = await answer(tc, first, reply, QUESTION)
            assert kinds(second)[-1] == "completed"
            assert _reply(second) == "Declined"
            assert source.answers == [reply]

    run(go())


@pytest.mark.parametrize("style", STYLES)
def test_cancel_while_paused(style: str) -> None:
    async def go() -> None:
        source = _source(style)
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write the report")
            task = await tc.client.cancel_task(CancelTaskRequest(id=ids(first)["task_id"]))
            assert task.status.state == TaskState.TASK_STATE_CANCELED
            if style == "live":
                (seen,) = source.answers
                assert seen.outcome == "declined" and seen.id == "q-1"
            else:
                assert source.answers == []

    run(go())


def test_the_wire_is_the_same_for_both_styles() -> None:
    async def flow(style: str) -> list[dict[str, Any]]:
        async with serve(SourceExecutor(_source(style)), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write the report")
            second = await answer(tc, first, _person(QUESTION, title="October"), QUESTION)
            return wire(first + second)

    assert run(flow("checkpoint")) == run(flow("live"))


class Big:
    """Sends a reply, or a file, larger than the limit the door is given."""

    pause = "live"
    card = CARD

    def __init__(self, what: str) -> None:
        self.what = what
        self.cancelled = False

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        if self.what == "reply":
            yield ReplyChunk("x" * 64)
        else:
            yield ArtifactEvent("f", ArtifactMeta(presentation="file"), (BytesContent(b"x" * 64, "text/plain"),))
        try:  # wait to be cancelled; the run is cancelled by the door, or this times out
            await asyncio.wait_for(ctx.cancelled.wait(), 2.0)
        finally:
            self.cancelled = ctx.cancelled.is_set()
        yield ReplyChunk("never sent")

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise NotImplementedError


@pytest.mark.parametrize("what", ["reply", "file"])
def test_content_over_the_limit_fails_the_task(what: str) -> None:
    async def go() -> None:
        source = Big(what)
        executor = SourceExecutor(source, limits=Limits(message_bytes=32))
        async with serve(executor, _card()) as served, a2a_client(served) as tc:
            events = await send(tc, "Go")
            assert kinds(events) == ["task", "failed"]  # R2C-SAFETY-4: nothing over the limit is sent
            text = events[-1].status_update.status.message.parts[0].text
            assert "32 B" in text or "larger than" in text
            assert source.cancelled

    run(go())


def test_the_extension_is_echoed() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(_source("live")), _card()) as served, a2a_client(served) as tc:
            first = await _paused(tc, "Write the report")
            await answer(tc, first, _person(QUESTION, title="October"), QUESTION)
            assert tc.echoed() == [URI, URI]

    run(go())
