"""Threads per owner and context, and one unfinished task per context (spec 003, story 4).

- Two owners on the same `contextId` get two threads (R2C-ID-1, FR-017), and neither reads the
  other's task (SC-005).
- A second unfinished task in a context is rejected, naming the first (R2C-ID-2, O9, FR-018).
- Once the first task ends, the same `contextId` opens a new task on the same thread (FR-019).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types.a2a_pb2 import GetTaskRequest, StreamResponse, TaskState
from a2a.utils.errors import TaskNotFoundError
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.core import Answer, RunContext, RunEvent, RunInput, thread_id

from a2a_harness import a2a_client, answer, ids, kinds, run, send, serve
from fake_sources import CARD, QUESTION, CheckpointFake


class Recorder(CheckpointFake):
    """A checkpoint fake that records the thread of every run it starts."""

    def __init__(self) -> None:
        super().__init__({})
        self.threads: list[str] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.threads.append(ctx.thread_id)
        async for event in super().run(input, ctx):
            yield event


def _card() -> Any:
    return agent_card(CARD, "https://remote.example.com/")


def _text(event: StreamResponse) -> str:
    return "".join(p.text for p in event.status_update.status.message.parts if p.HasField("text"))


def _title(value: str) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"title": value})


def test_two_owners_on_one_context_get_two_threads() -> None:
    async def go() -> None:
        source = Recorder()
        async with serve(SourceExecutor(source), _card()) as served, \
                a2a_client(served, user="alice") as alice, a2a_client(served, user="bob") as bob:
            first = await send(alice, "Write the report", context_id="ctx-1")
            other = await send(bob, "Write the report", context_id="ctx-1")
            assert kinds(first)[-1] == kinds(other)[-1] == "input_required"
            assert source.threads == [thread_id("a2a", "alice", "ctx-1"), thread_id("a2a", "bob", "ctx-1")]
            assert source.threads[0] != source.threads[1]
            with pytest.raises(TaskNotFoundError):  # SC-005
                await bob.client.get_task(GetTaskRequest(id=ids(first)["task_id"]))

    run(go())


def test_a_second_unfinished_task_is_rejected() -> None:
    async def go() -> None:
        source = Recorder()
        async with serve(SourceExecutor(source), _card()) as served, \
                a2a_client(served, user="alice") as alice, a2a_client(served, user="bob") as bob:
            first = await send(alice, "Write the report", context_id="ctx-1")
            task_a = ids(first)["task_id"]

            second = await send(alice, "And another one", context_id="ctx-1")
            assert kinds(second) == ["task", "rejected"]  # R2C-ID-2
            assert ids(second)["task_id"] != task_a
            assert task_a in _text(second[-1])
            assert len(source.threads) == 1  # the source never saw the second message

            still = await alice.client.get_task(GetTaskRequest(id=task_a))
            assert still.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
            done = await answer(alice, first, _title("October"), QUESTION)
            assert kinds(done)[-1] == "completed"

            theirs = await send(bob, "Write the report", context_id="ctx-1")  # another owner
            assert kinds(theirs) == ["task", "working", "input_required"]

    run(go())


def test_a_follow_up_after_the_end_opens_a_new_task_on_the_same_thread() -> None:
    async def go() -> None:
        source = Recorder()
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, user="alice") as alice:
            first = await send(alice, "Write the report", context_id="ctx-1")
            done = await answer(alice, first, _title("October"), QUESTION)
            assert kinds(done)[-1] == "completed"

            follow = await send(alice, "Now do the same for November.", context_id="ctx-1")  # R2C-A2A-7
            assert kinds(follow) == ["task", "working", "input_required"]
            assert ids(follow)["task_id"] != ids(first)["task_id"]
            assert ids(follow)["context_id"] == "ctx-1"
            assert source.threads == [thread_id("a2a", "alice", "ctx-1")] * 2

    run(go())


def test_two_new_messages_at_once_give_one_task_and_one_rejection() -> None:
    async def go() -> None:
        source = Recorder()
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, user="alice") as alice:
            both = await asyncio.gather(send(alice, "Write the report", context_id="ctx-1"),
                                        send(alice, "Write the report", context_id="ctx-1"))
            ends = sorted(kinds(events)[-1] for events in both)
            assert ends == ["input_required", "rejected"]
            assert len(source.threads) == 1

    run(go())
