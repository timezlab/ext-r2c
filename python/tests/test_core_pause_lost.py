"""`PauseLost`, the core's one addition for spec 006 (D2): a checkpoint source raises it in `resume`
when it holds no stopping point for the answer, and the driver ends the run `lost`. This file imports
no bridge and no door, so it runs in the core-only environment too."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import ext_r2c.core
from agent_source_suite import ASK_QUESTION, THREAD, TITLE, name, rest, until_pause
from ext_r2c.core import Answer, Ask, Driver, Error, PauseLost, RunContext, RunEvent, RunInput
from fake_sources import QUESTION, CheckpointFake, LiveFake

LOST = "The pause for q-1 was lost; ask again."


class Losing(CheckpointFake):
    """A checkpoint source that has no stopping point when the answer comes."""

    def __init__(self, store: dict[str, Any], error: Exception) -> None:
        super().__init__(store)
        self.error = error

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.answers.append(answer)
        raise self.error
        yield  # pragma: no cover - makes this an async generator


class LosingLive(LiveFake):
    """A live source that raises it after its answer; the driver does not look at the style."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        await ctx.ask(QUESTION)
        raise self.error
        yield  # pragma: no cover


async def _lost_after_the_answer(source: Any) -> list[RunEvent]:
    run = Driver(source).start(THREAD, ASK_QUESTION)
    events = await until_pause(run)
    await run.deliver(TITLE)
    events += await rest(run)
    return events


def _go(coro: Any) -> Any:
    return asyncio.run(asyncio.wait_for(coro, 10.0))


def test_a_lost_pause_ends_the_run_lost() -> None:
    async def go() -> None:
        driver = Driver(Losing({}, PauseLost(LOST)))
        run = driver.start(THREAD, ASK_QUESTION)
        events = await until_pause(run)
        assert isinstance(events[-1], Ask)
        await run.deliver(TITLE)
        events += await rest(run)
        assert [name(e) for e in events] == ["activity", "ask", "answer", "error:lost"]
        error = events[-1]
        assert isinstance(error, Error) and error.code == "lost" and error.reason == LOST
        assert run.pending is None
        # nothing after the end, and the thread is free: a new run starts on it
        again = driver.start(THREAD, ASK_QUESTION)
        assert isinstance(again.thread_id, str)
        await again.cancel()

    _go(go())


def test_an_empty_message_gets_a_reason() -> None:
    events = _go(_lost_after_the_answer(Losing({}, PauseLost())))
    error = events[-1]
    assert isinstance(error, Error) and error.code == "lost"
    assert error.reason == "The paused run was lost; ask again."


def test_a_resume_without_a_run_ends_lost_too() -> None:
    # the restart path: the driver holds no run, the source holds no stopping point
    async def go() -> None:
        source = Losing({}, PauseLost(LOST))
        events = await rest(Driver(source).resume(THREAD, QUESTION, TITLE))
        assert [name(e) for e in events] == ["answer", "error:lost"]
        assert events[-1] == Error("lost", LOST)

    _go(go())


def test_another_exception_still_ends_failed() -> None:
    events = _go(_lost_after_the_answer(Losing({}, RuntimeError("the agent broke"))))
    assert [name(e) for e in events] == ["activity", "ask", "answer", "error:failed"]
    error = events[-1]
    assert isinstance(error, Error) and error.reason == "the agent broke"


def test_a_live_source_raising_it_ends_lost() -> None:
    events = _go(_lost_after_the_answer(LosingLive(PauseLost(LOST))))
    assert [name(e) for e in events] == ["ask", "answer", "error:lost"]
    assert events[-1] == Error("lost", LOST)


def test_pause_lost_is_public() -> None:
    assert issubclass(PauseLost, Exception)
    assert ext_r2c.core.PauseLost is PauseLost
    assert "PauseLost" in ext_r2c.core.__all__
    assert PauseLost.__module__ == "ext_r2c.core.source"
    assert str(PauseLost(LOST)) == LOST
