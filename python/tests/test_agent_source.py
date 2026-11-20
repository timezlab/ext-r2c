"""Both fake sources pass the same `AgentSource` suite through one `Driver` (spec 002, story 4,
SC-005); thread ids keep owners and doors apart (R11); events are frozen."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from agent_source_suite import ASK_QUESTION, SCENARIOS, THREAD, TITLE, MakeSource, until_pause
from ext_r2c.core import (
    BytesContent,
    Done,
    Driver,
    Error,
    ReplyChunk,
    TextContent,
    UrlContent,
    thread_id,
)
from fake_sources import CheckpointFake, LiveFake


def _checkpoint() -> MakeSource:
    store: dict[str, Any] = {}
    return lambda **options: CheckpointFake(store, **options)


def _live() -> MakeSource:
    return lambda **options: LiveFake(**options)


FAKES: dict[str, Callable[[], MakeSource]] = {"checkpoint": _checkpoint, "live": _live}


@pytest.mark.parametrize("fake", list(FAKES))
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.__name__.removeprefix("scenario_") for s in SCENARIOS])
def test_suite(scenario: Callable[[MakeSource], None], fake: str) -> None:
    scenario(FAKES[fake]())


def test_thread_id() -> None:
    base = thread_id("a2a", "owner-1", "ctx-1")
    assert base == thread_id("a2a", "owner-1", "ctx-1")
    assert base.startswith("a2a:") and len(base) == len("a2a:") + 32
    assert thread_id("mcp", "owner-1", "ctx-1").startswith("mcp:")
    others = {thread_id("mcp", "owner-1", "ctx-1"), thread_id("a2a", "owner-2", "ctx-1"),
              thread_id("a2a", "owner-1", "ctx-2")}
    assert base not in others and len(others) == 3
    assert thread_id("a2a", "a:b", "c") != thread_id("a2a", "a", "b:c")
    assert "owner-1" not in base
    with pytest.raises(ValueError):
        thread_id("smtp", "owner-1", "ctx-1")  # type: ignore[arg-type]


def test_driver_refuses_a_source_without_a_style() -> None:
    class Eager(LiveFake):
        pause = "eager"  # type: ignore[assignment]

    class NoStyle:
        card = None

    with pytest.raises(TypeError):
        Driver(Eager())
    with pytest.raises(TypeError):
        Driver(NoStyle())  # type: ignore[arg-type]


def test_a_thread_runs_one_run_at_a_time() -> None:
    async def go() -> None:
        driver = Driver(LiveFake())
        run = driver.start(THREAD, ASK_QUESTION)
        await until_pause(run)
        assert run.pending is not None
        with pytest.raises(ValueError):
            driver.start(THREAD, ASK_QUESTION)
        with pytest.raises(ValueError):
            driver.resume(THREAD, run.pending, TITLE)  # held: answer it with Run.deliver
        await run.cancel()
        driver.start(THREAD, ASK_QUESTION)  # the thread is free again

    asyncio.run(go())


def test_events_are_frozen() -> None:
    events = [ReplyChunk("Hi"), Done(), Error("failed", "It broke."), TextContent("Hi"),
              BytesContent(b"\x00", "application/octet-stream"), UrlContent("https://example.com/a.csv", "text/csv")]
    for event in events:
        assert not hasattr(event, "__dict__")  # slots
        field = dataclasses.fields(event)[0].name if dataclasses.fields(event) else None
        if field:
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(event, field, "changed")
    assert TextContent("Hi").media_type == "text/plain"


def test_reply_chunk_last() -> None:
    # spec 003 research R5: the source marks the reply's final chunk.
    assert ReplyChunk("x").last is False
    chunk = ReplyChunk("x", last=True)
    assert chunk.last is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.last = False  # type: ignore[misc]
