"""A new message while an approval is pending (spec 006, story 5; R11; FR-007; D9; SC-009).

The model here is `strict`: like a real provider it refuses a history that holds a tool call nothing
answers. So a test that reaches a normal reply proves the pending call was settled before the new
message was sent, and the same test fails without the settle (the mutation check of the phase).

Real `create_agent` graphs with LangChain's own middleware in both modes, a real checkpointer and the
real `Driver`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import interrupt

from ext_r2c.bridges.langgraph._settle import settle
from ext_r2c.core import Approval, Ask, Done, Driver, Error, RunInput

from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import DEPLOY, NOTICE, agent, memory_saver, run, wrap
from langgraph_models import Call, Say, Scripted, Turn, dangling, humans, tool_results
from test_langgraph_approvals import (
    CONFIG,
    MODES,
    THREAD,
    allow,
    pause_at,
    tool_message,
    world,
)

WITHDRAWN = "withdrawn"


def two_calls(messages: list[BaseMessage]) -> Turn:
    """An ungated call, then a gated one; after anything else the model says what the tools said."""
    if humans(messages) == 1 and not tool_results(messages):
        return Call((NOTICE, {"text": "hi"}), (DEPLOY, {"version": "1.2"}))
    told = " | ".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
    return Say(f"finished. {told}")


async def interrupted(w: Any) -> Any:
    """Pause at the first approval, then abandon the run: the pause is what the thread holds."""
    live, asked = await pause_at(w)
    assert isinstance(asked, Approval)
    await live.cancel()
    return asked


async def new_message(w: Any, text: str = "again") -> list[Any]:
    return [e async for e in Driver(w.source).start(THREAD, RunInput(text))]


# --- 1. SC-009: the model never sees a call with no answer ----------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_a_new_message_on_a_pending_approval_reaches_a_normal_reply(mode: str) -> None:
    w = world(two_calls, mode, {DEPLOY: True}, strict=True)

    async def go() -> None:
        await interrupted(w)
        assert dangling(await w.messages()), "the thread holds calls nothing answers: a strict model would refuse it"

        events = await new_message(w)
        assert isinstance(events[-1], Done), events
        assert not [e for e in events if isinstance(e, (Ask, Error))]
        assert reply_text(events).startswith("finished.")
        assert dangling(await w.messages()) == [], "every call has an answer now"
        assert not (await w.state()).interrupts, "the old pause is gone"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_the_model_sees_the_withdrawn_call_as_rejected_with_the_reason(mode: str) -> None:
    w = world(two_calls, mode, {DEPLOY: True}, strict=True)

    async def go() -> None:
        await interrupted(w)
        events = await new_message(w)
        assert WITHDRAWN in reply_text(events), "the reason went to the model with the call's answer"
        messages = await w.messages()
        gone = tool_message(messages, "call-0-1")
        assert gone.name == DEPLOY and gone.status == "error", "rejected, in the way a denied call is"
        assert WITHDRAWN in gone.text and "new message" in gone.text
        assert [m.text for m in messages if isinstance(m, HumanMessage)] == ["go", "again"], "the new message follows"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_what_already_ran_is_kept_and_what_did_not_is_withdrawn(mode: str) -> None:
    """per_call: the ungated call ran inside the unfinished step, and its own message is kept; batched:
    nothing ran yet, so both are withdrawn."""
    w = world(two_calls, mode, {DEPLOY: True}, strict=True)

    async def go() -> None:
        await interrupted(w)
        await new_message(w)
        messages = await w.messages()
        notice, deploy = tool_message(messages, "call-0-0"), tool_message(messages, "call-0-1")
        assert not w.runs[DEPLOY] and deploy.status == "error"
        if mode == "per_call":
            assert w.runs[NOTICE] == 1 and notice.text == "sent: hi" and notice.status != "error"
        else:
            assert not w.runs[NOTICE] and notice.status == "error" and WITHDRAWN in notice.text

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_pause_with_two_gated_calls_withdraws_both(mode: str) -> None:
    w = world(two_calls, mode, {DEPLOY: True, NOTICE: True}, strict=True)

    async def go() -> None:
        await interrupted(w)
        events = await new_message(w)
        assert isinstance(events[-1], Done) and not w.runs, "nothing ran: both calls were withdrawn"
        messages = await w.messages()
        assert [tool_message(messages, c).status for c in ("call-0-0", "call-0-1")] == ["error", "error"]

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_the_withdrawn_pause_cannot_be_answered_any_more(mode: str) -> None:
    w = world(two_calls, mode, {DEPLOY: True}, strict=True)

    async def go() -> None:
        asked = await interrupted(w)
        await new_message(w)
        calls = w.calls.n
        events = [e async for e in Driver(w.source).resume(THREAD, asked, allow(asked))]
        assert isinstance(events[-1], Error) and events[-1].code == "lost", events
        assert w.calls.n == calls and not w.runs[DEPLOY], "the late answer called nothing"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_new_message_after_an_answered_pause_is_not_touched(mode: str) -> None:
    """Nothing to settle once the approvals are answered: no message is withdrawn."""
    w = world(two_calls, mode, {DEPLOY: True}, strict=True)

    async def go() -> None:
        live, asked = await pause_at(w)
        await live.deliver(allow(asked))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        before = await w.messages()
        events = await new_message(w)
        assert isinstance(events[-1], Done)
        after = await w.messages()
        assert [m.id for m in after[: len(before)]] == [m.id for m in before]
        assert not [m for m in after if isinstance(m, ToolMessage) and WITHDRAWN in m.text]

    run(go())


# --- 2. the batch in progress goes with the pause ---------------------------------------------------------


def test_a_batch_in_progress_is_dropped_when_the_pause_is_withdrawn() -> None:
    w = world(two_calls, "batched", {DEPLOY: True, NOTICE: True}, strict=True)

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        await live.deliver(allow(first))
        await until_pause(live)
        interrupt_id = (await w.state()).interrupts[0].id
        assert w.source._batches.get(THREAD, interrupt_id) is not None, "one decision is on record"
        await live.cancel()

        events = await new_message(w)
        assert isinstance(events[-1], Done)
        assert not len(w.source._batches), "the record of a batch that is no more is gone"

    run(go())


# --- 3. other kinds of pause are left as LangGraph leaves them --------------------------------------------


def test_a_hand_written_interrupt_is_not_settled() -> None:
    """Only a middleware approval is withdrawn (FR-007): nothing is written for any other pause."""

    @tool("ask_it")
    def ask_it() -> str:
        """Ask the caller something."""
        return f"got {interrupt('Which region?')}"

    def script(messages: list[BaseMessage]) -> Turn:
        return Call(("ask_it", {})) if humans(messages) == 1 and not tool_results(messages) else Say("ok")

    graph = agent(Scripted(script=script), [ask_it], memory_saver())
    source = wrap(graph)

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        await until_pause(live)
        assert live.pending is not None
        await live.cancel()
        before = len((await graph.aget_state(CONFIG)).values["messages"])
        events = [e async for e in Driver(source).start(THREAD, RunInput("again"))]
        assert isinstance(events[-1], Done) and not [e for e in events if isinstance(e, (Ask, Error))], events
        messages = (await graph.aget_state(CONFIG)).values["messages"]
        assert [type(m).__name__ for m in messages[before:]] == ["HumanMessage", "AIMessage"], (
            "the new message and the reply: no message was written for the call that waited"
        )
        assert not [m for m in messages if isinstance(m, ToolMessage)]

    run(go())


# --- 4. the write itself ---------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_settle_leaves_no_pause_and_is_the_step_that_was_waiting(mode: str) -> None:
    """Written with no `as_node` (R11), so it is recorded as the step that was waiting. With `per_call` that is
    the tools step, and the thread then stands where that step would have left it: the model is next. (With
    `batched` the waiting step is the middleware's own, which any `as_node` of the agent gives as well.)"""
    w = world(two_calls, mode, {DEPLOY: True})

    async def go() -> None:
        await interrupted(w)
        state = await w.state()
        assert await settle(w.source._graph, THREAD, state) is True
        after = await w.state()
        assert not after.interrupts, "the pause is gone"
        if mode == "per_call":
            assert state.next == ("tools",) and after.next == ("model",)

    run(go())


class _Graph:
    """Only what the settle calls, and a record of it."""

    def __init__(self) -> None:
        self.writes: list[Any] = []

    async def aupdate_state(self, config: Any, values: Any, *args: Any, **kwargs: Any) -> None:
        self.writes.append(values)


def test_nothing_is_written_when_the_calls_are_not_in_the_graphs_own_messages() -> None:
    """An agent that is a node of another graph: the middleware's pause is there, the calls are not this
    graph's messages, so there is nothing to answer here and no empty write is made."""
    pause = SimpleNamespace(value={"tool_call_id": "c1", "name": DEPLOY, "args": {}, "description": "d"})
    state = SimpleNamespace(interrupts=[pause], values={"messages": []}, tasks=[])
    graph = _Graph()

    assert run(settle(graph, THREAD, state)) is False
    assert graph.writes == []
