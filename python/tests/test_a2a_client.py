"""The caller's A2A client against the door and against chosen wires (spec 003, story 5).

- Reading: typed items in wire order; unknown kinds and unknown activity types are skipped
  (FR-021, R2C-CORE-5, R2C-CORE-6).
- Answering: checked before sending, never an approval as `caller` (FR-022).
- Reattaching after a cut, and reading the task back (FR-023, `resubscribe.json`).
- Fetching artifact files from the connection's own origin only (FR-025, SC-008).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.types.a2a_pb2 import TaskState
from ext_r2c.a2a import (
    ActivityItem,
    AnswerRejected,
    ArtifactItem,
    Link,
    R2CClient,
    ReplyItem,
    RequestItem,
    SourceExecutor,
    StatusItem,
    TaskItem,
    TooLarge,
    UsageItem,
    agent_card,
)
from ext_r2c.a2a._codec import artifact_update
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    ArtifactMeta,
    BytesContent,
    Limits,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    UrlContent,
    Usage,
    UsageEvent,
)
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from a2a_harness import TIMEOUT, URL, Served, WireExecutor, example_events, run, serve, status
from a2a_transport import StreamingASGITransport
from fake_sources import APPROVAL, CARD, QUESTION, LiveFake


@dataclass
class Counting(httpx.AsyncBaseTransport):
    """The streaming transport, recording every request."""

    inner: StreamingASGITransport
    requests: list[httpx.Request] = field(default_factory=list)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.inner.handle_async_request(request)

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


@contextlib.asynccontextmanager
async def _client(served: Served, *, limits: Limits = Limits()) -> AsyncIterator[tuple[R2CClient, Counting]]:
    transport = Counting(StreamingASGITransport(served.app))
    http = httpx.AsyncClient(transport=transport, headers={"Authorization": "Bearer alice"}, timeout=TIMEOUT)
    client = await R2CClient.connect(URL, httpx_client=http, limits=limits)
    try:
        yield client, transport
    finally:
        await client.aclose()
        await http.aclose()


def _card() -> Any:
    return agent_card(CARD, URL)


async def _all(items: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in items]


def _person(**value: Any) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value=value)


def _step(state: str) -> ActivityEvent:
    return ActivityEvent(Activity.parse({"kind": "activity", "id": "step-1", "type": "step",
                                         "label": "Preparing", "state": state}))


class Gated:
    """A live source that waits on `gate` after its first activity, then asks `QUESTION`."""

    pause = "live"
    card = CARD

    def __init__(self) -> None:
        self.gate = asyncio.Event()

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield _step("running")
        await self.gate.wait()
        yield _step("done")
        answer = await ctx.ask(QUESTION)
        yield ReplyChunk(f"Got: {(answer.value or {}).get('title')}", last=True)
        yield UsageEvent(Usage(output_tokens=3))

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise NotImplementedError


# --- Reading ----------------------------------------------------------------------------------


def test_the_question_flow_reads_as_typed_items() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(LiveFake()), _card()) as served, _client(served) as (client, _):
            items = await _all(client.send("Write the report", context_id="ctx-1"))
            assert [type(i) for i in items] == [TaskItem, StatusItem, ActivityItem, StatusItem, RequestItem]
            task, working, activity, asked, request = items
            assert task.context_id == "ctx-1" and task.task_id
            assert working.state == "working" and working.text
            assert activity.activity.type == "step"
            assert asked.state == "input_required"
            assert request.request == QUESTION
            assert client.pending == QUESTION
            assert (client.task_id, client.context_id) == (task.task_id, "ctx-1")  # R2C-ID-3
            assert client.active  # the door echoed the URI

    run(go())


def test_unknown_kinds_and_activity_types_are_skipped(standard_dir: Path) -> None:
    events = example_events(standard_dir / "examples" / "a2a" / "unknown-kind-ignored.json")
    executor = WireExecutor(*events, status(TaskState.TASK_STATE_COMPLETED, "Done."))

    async def go() -> None:
        async with serve(executor, _card()) as served, _client(served) as (client, _):
            items = await _all(client.send("Read the inventory"))
            activities = [i.activity for i in items if isinstance(i, ActivityItem)]
            assert [a.id for a in activities] == ["call-1"]  # `plan-1` has an unknown type
            assert client.skipped == 2  # the `provenance` Part and the `plan` activity
            assert isinstance(items[-1], StatusItem) and items[-1].state == "completed"

    run(go())


# --- Answering --------------------------------------------------------------------------------


def test_a_bad_answer_is_refused_before_sending() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(LiveFake()), _card()) as served, _client(served) as (client, seen):
            await _all(client.send("Write the report"))
            before = len(seen.requests)
            with pytest.raises(AnswerRejected) as caught:
                await _all(client.answer(_person()))  # the required title is missing
            assert [p.key for p in caught.value.problems] == ["title"]
            assert len(seen.requests) == before  # nothing was sent

    run(go())


def test_an_approval_is_never_answered_as_caller() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(LiveFake()), _card()) as served, _client(served) as (client, seen):
            await _all(client.send("Write and publish the report"))
            assert client.pending == APPROVAL
            before = len(seen.requests)
            by_caller = Answer(id="ap-1", outcome="answered", answered_by={"role": "caller"},
                               value={"decision": "allow"})
            with pytest.raises(AnswerRejected) as caught:
                await _all(client.answer(by_caller))
            assert [p.code for p in caught.value.problems] == ["caller_on_approval"]  # R2C-ANSWER-4
            assert len(seen.requests) == before

    run(go())


def test_a_good_answer_is_sent_with_the_task_and_text() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(LiveFake()), _card()) as served, _client(served) as (client, seen):
            await _all(client.send("Write the report", context_id="ctx-1"))
            task_id = client.task_id
            items = await _all(client.answer(_person(title="October")))
            sent = json.loads(seen.requests[-1].content)["params"]["message"]
            assert (sent["taskId"], sent["contextId"]) == (task_id, "ctx-1")  # R2C-A2A-2
            text, data = sent["parts"]
            assert text == {"text": "Title: October"}
            assert data["data"]["kind"] == "answer" and data["data"]["id"] == "q-1"
            assert [type(i) for i in items] == [ReplyItem, StatusItem, ActivityItem, StatusItem, UsageItem]
            assert items[0].text == "Got: October"
            assert items[-2].state == "completed"
            assert client.pending is None

    run(go())


# --- Reattaching ------------------------------------------------------------------------------


def test_reattach_after_a_cut_then_read_the_task_back() -> None:
    async def go() -> None:
        source = Gated()
        async with serve(SourceExecutor(source), _card()) as served, _client(served) as (client, _):
            async for item in client.send("Write the report"):
                if isinstance(item, ActivityItem):
                    break  # the stream is cut here
            items: list[Any] = []
            async for item in client.reattach():
                items.append(item)
                if len(items) == 1:
                    source.gate.set()
            assert isinstance(items[0], TaskItem) and items[0].state == "working"  # the snapshot
            assert isinstance(items[-1], RequestItem) and items[-1].request == QUESTION
            assert any(isinstance(i, StatusItem) and i.state == "input_required" for i in items)

            await _all(client.answer(_person(title="October")))
            back = await client.get_task()  # `resubscribe.json`: GetTask after the end
            assert isinstance(back[0], TaskItem) and back[0].state == "completed"
            assert UsageItem(Usage(output_tokens=3)) in back
            assert [i.text for i in back if isinstance(i, ReplyItem)] == ["Got: October"]

    run(go())


def test_cancel_gives_a_canceled_status() -> None:
    async def go() -> None:
        async with serve(SourceExecutor(LiveFake()), _card()) as served, _client(served) as (client, _):
            await _all(client.send("Write the report"))
            done = await client.cancel()
            assert isinstance(done, StatusItem) and done.state == "canceled"

    run(go())


# --- Fetching ---------------------------------------------------------------------------------

OWN = "https://remote.example.com/files/report.csv"
OTHER = "https://other.example.com/x"
FILE = ArtifactMeta(presentation="file")


def _files(*contents: Any) -> WireExecutor:
    updates = [artifact_update("", "", f"f-{n}", (c,), meta=FILE, last_chunk=True) for n, c in enumerate(contents)]
    return WireExecutor(*updates, status(TaskState.TASK_STATE_COMPLETED, "Done."))


def _serve_file(served: Served, body: bytes, *, chunks: int = 1) -> None:
    async def endpoint(request: Request) -> Response:
        async def gen() -> AsyncIterator[bytes]:
            for _ in range(chunks):
                yield body

        return StreamingResponse(gen(), media_type="text/csv")

    served.app.router.routes.append(Route("/files/report.csv", endpoint))


def test_fetch_reads_own_origin_only() -> None:
    executor = _files(UrlContent(OWN, "text/csv", "report.csv"), UrlContent(OTHER, "text/csv", "x"),
                      BytesContent(b"a,b\n", "text/csv", "raw.csv"))

    async def go() -> None:
        async with serve(executor, _card()) as served, _client(served) as (client, seen):
            _serve_file(served, b"item,count\n")
            files = [i for i in await _all(client.send("Files")) if isinstance(i, ArtifactItem)]
            own, other, raw = files
            assert await client.fetch(own) == b"item,count\n"
            assert await client.fetch(other) == Link(OTHER, "text/csv", "x")
            assert await client.fetch(raw) == b"a,b\n"
            assert "other.example.com" not in seen.hosts()  # SC-008

    run(go())


def test_fetch_stops_at_the_limit() -> None:
    executor = _files(UrlContent(OWN, "text/csv", "report.csv"), BytesContent(b"x" * 64, "text/csv", "raw.csv"))

    async def go() -> None:
        async with serve(executor, _card()) as served, _client(served, limits=Limits(file_bytes=10)) as (client, _):
            _serve_file(served, b"12345678", chunks=100)
            own, raw = [i for i in await _all(client.send("Files")) if isinstance(i, ArtifactItem)]
            assert isinstance(await client.fetch(own), TooLarge)  # R2C-SAFETY-5
            assert await client.fetch(raw) == TooLarge(64)

    run(go())
