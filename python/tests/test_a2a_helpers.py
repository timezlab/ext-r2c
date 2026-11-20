"""A hand-written a2a-sdk executor that speaks R2C through `R2CTask` (spec 003, story 6).

`HandWritten` is not an `AgentSource`: it follows contracts/a2a-api.md "An executor written by
hand". It must give the same R2C wire as `SourceExecutor` for the same events (SC-007), and the
same answer rules, since `SourceExecutor` is built on the same helpers (FR-026, FR-027).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from ext_r2c import URI
from ext_r2c.a2a import PendingMemory, R2CTask, SourceExecutor, agent_card
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    ArtifactEvent,
    ArtifactMeta,
    BytesContent,
    RunContext,
    RunEvent,
    RunInput,
    Usage,
    UsageEvent,
)

from a2a_harness import a2a_client, answer, ids, kinds, run, send, serve, wire
from fake_sources import CARD, QUESTION

RUNNING = Activity.parse({"kind": "activity", "id": "step-1", "type": "step", "label": "Preparing", "state": "running"})
REPORT = ArtifactEvent("report", ArtifactMeta(presentation="file"),
                       (BytesContent(b"item,count\n", "text/csv", "report.csv"),), name="report.csv")
USAGE = Usage(output_tokens=3)


class HandWritten(AgentExecutor):
    """Asks `q-1`, then delivers one file, reports usage and completes; a2a-sdk and `R2CTask`
    only."""

    def __init__(self, store: TaskStore | None = None) -> None:
        self.memory = PendingMemory()
        self.store = store
        self.answers: list[Answer] = []

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = R2CTask(context, event_queue, memory=self.memory)
        if context.current_task is None:
            if not await task.open(store=self.store, owner_resolver=resolve_user_scope):
                return
            await task.activity(RUNNING)
            await task.ask(QUESTION)
            return
        reply = await task.take_answer()
        if reply is None:
            return  # re-asked or refused already
        self.answers.append(reply)
        await task.artifact(REPORT)
        await task.usage(USAGE)
        await task.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await R2CTask(context, event_queue, memory=self.memory).cancelled()


class Scripted:
    """The same events as `HandWritten`, as a live source."""

    pause = "live"
    card = CARD

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield ActivityEvent(RUNNING)
        await ctx.ask(QUESTION)
        yield REPORT
        yield UsageEvent(USAGE)

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise NotImplementedError


def _card() -> Any:
    return agent_card(CARD, "https://remote.example.com/")


def _title(value: str) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"title": value})


async def _flow(executor: AgentExecutor, *, r2c: bool = True) -> list[Any]:
    async with serve(executor, _card()) as served, a2a_client(served, r2c=r2c) as tc:
        first = await send(tc, "Write the report")
        if r2c:
            second = await answer(tc, first, _title("October"), QUESTION)
        else:
            second = await send(tc, "October", **ids(first))
        assert kinds(first) == ["task", "working", "input_required"]
        assert kinds(second) == ["artifact:report", "completed"]
        return wire(first + second)


def test_the_same_wire_as_the_source_executor() -> None:
    hand = HandWritten()
    assert run(_flow(hand)) == run(_flow(SourceExecutor(Scripted())))  # SC-007
    assert hand.answers == [_title("October")]


def test_without_activation_the_wire_is_text_only() -> None:
    hand = HandWritten()
    events = run(_flow(hand, r2c=False))
    assert URI not in json.dumps(events)  # R2C-ACT-3
    (got,) = hand.answers  # the text answer, R2C-ASK-8
    assert got.value == {"title": "October"}


def test_a_bad_answer_is_re_asked_by_the_helper() -> None:
    async def go() -> None:
        hand = HandWritten()
        async with serve(hand, _card()) as served, a2a_client(served) as tc:
            first = await send(tc, "Write the report")
            empty = Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={})
            again = await answer(tc, first, empty, QUESTION)
            assert kinds(again) == ["input_required"]  # R2C-ASK-6
            assert hand.answers == []

            done = await answer(tc, first, _title("October"), QUESTION)
            assert kinds(done)[-1] == "completed"
            assert hand.answers == [_title("October")]

    run(go())


def test_open_with_the_store_rejects_a_second_task() -> None:
    async def go() -> None:
        store = InMemoryTaskStore(owner_resolver=resolve_user_scope)
        async with serve(HandWritten(store), _card(), store=store) as served, a2a_client(served, user="alice") as tc:
            first = await send(tc, "Write the report", context_id="ctx-1")
            second = await send(tc, "And another", context_id="ctx-1")
            assert kinds(second) == ["task", "rejected"]  # R2C-ID-2
            assert ids(first)["task_id"] in second[-1].status_update.status.message.parts[0].text

    run(go())
