"""The shared `AgentSource` suite on a real graph, and the wrapper that drives it
(spec 006, D3 c; SC-001; contracts/suite-changes.md).

`SuiteSource` is the test-only wrapper of `langgraph_suite_source.py`: a real `LangGraphAgent` over a
real graph, plus the three things the suite asks of a source (`answers`, `fail_after_ask`,
`double_ask`). The same scenarios run on the two fakes in `test_agent_source.py`.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ext_r2c.core import AgentSource, Driver, Error

from agent_source_suite import (
    ALLOW,
    ASK_APPROVAL,
    ASK_QUESTION,
    DENY,
    SCENARIOS,
    THREAD,
    TITLE,
    check_sequence,
    reply_text,
    rest,
    shape,
    until_pause,
)
from langgraph_graphs import run
from langgraph_suite_source import SuiteSource


def _store() -> Callable[..., AgentSource]:
    """A `make_source`: every source it makes is the same remote, over one in-memory checkpointer."""
    saver = InMemorySaver()
    return lambda **options: SuiteSource(saver, **options)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_the_shared_suite_passes_on_a_real_graph(scenario: Callable[[Callable[..., AgentSource]], None]) -> None:
    scenario(_store())


# --- the wrapper's own behaviour ---------------------------------------------------------------


def test_the_wrapper_is_a_checkpoint_source_with_the_agents_card() -> None:
    source = _store()()
    assert source.pause == "checkpoint"
    assert source.card.name == "suite" and source.card.version == "0.0.0"


def test_answers_holds_what_reached_resume_and_nothing_before() -> None:
    async def go() -> None:
        source = _store()()
        live = Driver(source).start(THREAD, ASK_APPROVAL)
        await until_pause(live)
        assert source.answers == []  # type: ignore[attr-defined]
        await live.deliver(DENY)
        await rest(live)
        assert source.answers == [DENY]  # type: ignore[attr-defined]

    run(go())


def test_answers_is_empty_after_a_cancel() -> None:
    async def go() -> None:
        source = _store()()
        live = Driver(source).start(THREAD, ASK_QUESTION)
        await until_pause(live)
        await live.cancel()
        assert source.answers == []  # type: ignore[attr-defined]

    run(go())


def test_double_ask_makes_the_driver_end_the_run_with_a_protocol_error() -> None:
    async def go() -> None:
        live = Driver(_store()(double_ask=True)).start(THREAD, ASK_QUESTION)
        events = await rest(live)
        check_sequence(events)
        assert shape(events) == ["ask", "error:protocol"]
        assert live.pending is None

    run(go())


def test_a_correct_source_asks_one_request_at_a_time() -> None:
    async def go() -> None:
        live = Driver(_store()()).start(THREAD, ASK_QUESTION)
        events = await until_pause(live)
        assert shape(events) == ["ask"]
        await live.deliver(TITLE)
        assert shape(await rest(live)) == ["answer", "reply", "usage", "done"]

    run(go())


def test_fail_after_ask_ends_the_run_failed_with_the_tools_message() -> None:
    async def go() -> None:
        live = Driver(_store()(fail_after_ask=True)).start(THREAD, ASK_APPROVAL)
        events = await until_pause(live)
        await live.deliver(ALLOW)
        events += await rest(live)
        assert shape(events) == ["ask", "answer", "error:failed"]
        error = events[-1]
        assert isinstance(error, Error) and "the agent broke" in error.reason

    run(go())


# --- a restart ---------------------------------------------------------------------------------


def test_a_restart_over_the_same_saver_keeps_the_pause() -> None:
    async def go() -> None:
        make = _store()
        first = Driver(make()).start(THREAD, ASK_QUESTION)
        await until_pause(first)
        request = first.pending
        assert request is not None
        later = make()  # a new graph and a new agent over the same checkpointer
        events = await rest(Driver(later).resume(THREAD, request, TITLE))
        assert shape(events) == ["answer", "reply", "usage", "done"]
        assert reply_text(events) == "Got: October stock"
        await first.cancel()

    run(go())


def test_a_restart_over_a_new_in_memory_saver_loses_the_pause() -> None:
    async def go() -> None:
        first = Driver(_store()()).start(THREAD, ASK_QUESTION)
        await until_pause(first)
        request = first.pending
        assert request is not None
        events = await rest(Driver(_store()()).resume(THREAD, request, TITLE))  # another saver: nothing is held
        assert shape(events) == ["answer", "error:lost"]
        await first.cancel()

    run(go())
