"""The `AgentSource` contract suite (contracts/agent-source-suite.md, scenarios S1-S10).

Each scenario takes `make_source(**options)`, which returns a new source each call; two sources
from one `make_source` are the same remote (a checkpoint source shares its store). Options:
`fail_after_ask`, `double_ask`. A source must record every answer that reached it in `answers`.
Only S5 and S7 read the source's declared `pause`; no source is special-cased.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import pytest

from ext_r2c.core import (
    ActivityEvent,
    AgentSource,
    Answer,
    AnswerEvent,
    Ask,
    Done,
    Driver,
    Error,
    ReplyChunk,
    Run,
    RunEvent,
    RunInput,
    UsageEvent,
    thread_id,
)

MakeSource = Callable[..., AgentSource]
TIMEOUT = 10.0  # seconds: a source that never answers the driver fails instead of hanging


def _run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))
T = TypeVar("T")
THREAD = thread_id("a2a", "owner-1", "ctx-1")
ASK_QUESTION = RunInput("Write the report")
ASK_APPROVAL = RunInput("Write the report and publish it")


def _answer(id: str, value: dict[str, Any] | None = None, role: str = "person") -> Answer:
    obj: dict[str, Any] = {"kind": "answer", "id": id, "answered_by": {"role": role}}
    obj.update({"outcome": "answered", "value": value} if value is not None else {"outcome": "declined"})
    return Answer.parse(obj)


TITLE = _answer("q-1", {"title": "October stock"})
ALLOW = _answer("ap-1", {"decision": "allow"})
DENY = _answer("ap-1", {"decision": "deny", "reason": "Not before Monday."})
DECLINED = _answer("q-1")


def name(event: RunEvent) -> str:
    """A short name per event; an error carries its code."""
    if isinstance(event, Error):
        return f"error:{event.code}"
    return {ActivityEvent: "activity", Ask: "ask", AnswerEvent: "answer", ReplyChunk: "reply",
            UsageEvent: "usage", Done: "done"}.get(type(event), type(event).__name__)


async def until_pause(run: Run) -> list[RunEvent]:
    """Events up to and including the first `Ask`, or to the end."""
    out: list[RunEvent] = []
    async for event in run:
        out.append(event)
        if isinstance(event, Ask):
            break
    return out


async def rest(run: Run) -> list[RunEvent]:
    """Every remaining event; then checks that the run stays ended (S10)."""
    out = [event async for event in run]
    with pytest.raises(StopAsyncIteration):
        await run.__anext__()
    return out


def check_sequence(events: list[RunEvent]) -> None:
    """S10: exactly one terminal event, and it is the last."""
    terminal = [i for i, e in enumerate(events) if isinstance(e, (Done, Error))]
    assert terminal == [len(events) - 1], [name(e) for e in events]


async def _answered(make_source: MakeSource, input: RunInput, answer: Answer) -> list[RunEvent]:
    run = Driver(make_source()).start(THREAD, input)
    events = await until_pause(run)
    assert run.pending is not None and run.pending.id == answer.id
    await run.deliver(answer)
    assert run.pending is None
    events += await rest(run)
    check_sequence(events)
    return events


def _replies(events: list[RunEvent]) -> list[str]:
    return [e.text for e in events if isinstance(e, ReplyChunk)]


FULL = ["activity", "ask", "answer", "reply", "activity", "usage", "done"]


def scenario_question_answered(make_source: MakeSource) -> None:  # S1
    events = _run(_answered(make_source, ASK_QUESTION, TITLE))
    assert [name(e) for e in events] == FULL
    assert _replies(events) == ["Got: October stock"]
    answer = events[2]
    assert isinstance(answer, AnswerEvent) and answer.answer == TITLE


def scenario_approval_allowed(make_source: MakeSource) -> None:  # S2
    events = _run(_answered(make_source, ASK_APPROVAL, ALLOW))
    assert [name(e) for e in events] == FULL
    assert _replies(events) == ["Done"]


def scenario_approval_denied_with_reason(make_source: MakeSource) -> None:  # S3
    async def go() -> None:
        source = make_source()
        events = await _answered(lambda: source, ASK_APPROVAL, DENY)
        assert [name(e) for e in events] == FULL
        assert _replies(events) == ["Not done: Not before Monday."]
        assert source.answers == [DENY]  # type: ignore[attr-defined]

    _run(go())


def scenario_declined(make_source: MakeSource) -> None:  # S4
    events = _run(_answered(make_source, ASK_QUESTION, DECLINED))
    assert [name(e) for e in events] == FULL
    assert _replies(events) == ["Declined"]


def scenario_cancelled_while_paused(make_source: MakeSource) -> None:  # S5
    async def go() -> None:
        source = make_source()
        run = Driver(source).start(THREAD, ASK_QUESTION)
        events = await until_pause(run)
        await run.cancel()
        events += await rest(run)
        check_sequence(events)
        assert [name(e) for e in events] == ["activity", "ask", "error:cancelled"]
        seen = source.answers  # type: ignore[attr-defined]
        if source.pause == "checkpoint":
            assert seen == []  # never resumed
        else:
            assert [a.outcome for a in seen] == ["declined"]
        with pytest.raises(ValueError):
            await run.deliver(TITLE)

    _run(go())


def scenario_delivered_with_nothing_pending(make_source: MakeSource) -> None:  # S6
    async def go() -> None:
        run = Driver(make_source()).start(THREAD, ASK_QUESTION)
        with pytest.raises(ValueError):
            await run.deliver(TITLE)  # nothing asked yet
        events = await until_pause(run)
        await run.deliver(TITLE)
        with pytest.raises(ValueError):
            await run.deliver(TITLE)  # already answered
        events += await rest(run)
        check_sequence(events)
        assert [name(e) for e in events] == FULL
        with pytest.raises(ValueError):
            await run.deliver(TITLE)  # ended

    _run(go())


def scenario_restart(make_source: MakeSource) -> None:  # S7
    async def go() -> None:
        first = Driver(make_source()).start(THREAD, ASK_QUESTION)
        await until_pause(first)
        request = first.pending
        assert request is not None
        later = make_source()  # the same remote after a restart
        events = await rest(Driver(later).resume(THREAD, request, TITLE))
        check_sequence(events)
        if later.pause == "checkpoint":
            assert [name(e) for e in events] == ["answer", "reply", "activity", "usage", "done"]
            assert _replies(events) == ["Got: October stock"]
        else:
            assert [name(e) for e in events] == ["error:lost"]
            error = events[0]
            assert isinstance(error, Error) and "lost" in error.reason
        await first.cancel()

    _run(go())


def scenario_raises_after_the_ask(make_source: MakeSource) -> None:  # S8
    async def go() -> None:
        run = Driver(make_source(fail_after_ask=True)).start(THREAD, ASK_QUESTION)
        events = await until_pause(run)
        await run.deliver(TITLE)
        events += await rest(run)
        check_sequence(events)
        assert [name(e) for e in events] == ["activity", "ask", "answer", "error:failed"]
        error = events[-1]
        assert isinstance(error, Error) and error.reason

    _run(go())


def scenario_second_ask_before_the_answer(make_source: MakeSource) -> None:  # S9
    async def go() -> None:
        run = Driver(make_source(double_ask=True)).start(THREAD, ASK_QUESTION)
        events = await rest(run)
        check_sequence(events)
        assert [name(e) for e in events] == ["activity", "ask", "error:protocol"]
        assert run.pending is None

    _run(go())


SCENARIOS = [
    scenario_question_answered,
    scenario_approval_allowed,
    scenario_approval_denied_with_reason,
    scenario_declined,
    scenario_cancelled_while_paused,
    scenario_delivered_with_nothing_pending,
    scenario_restart,
    scenario_raises_after_the_ask,
    scenario_second_ask_before_the_answer,
]
