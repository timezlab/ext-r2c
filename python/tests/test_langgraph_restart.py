"""A paused graph survives a restart (spec 006, story 3; FR-015, FR-019, FR-021; SC-003).

"Process A" runs a real graph to its ask on a real SQLite file and is dropped: its saver is closed, its
graph and its agent are gone. "Process B" is a new saver, a new graph and a new agent over the same file,
and answers with the request A had kept (`Driver.resume`, as a door does after a restart). The two
processes count into the same counters, so a test sees how many times a tool body or the model really ran.

What a restart must not change: the ids of the requests, the order they are asked in, the answer's
effect, and the number of times a tool runs. What it does change, and says so: a batch's half-given
decisions lived in A's memory, so the batch is asked again; an in-memory checkpointer holds nothing, so
the answer ends `lost`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from ext_r2c.bridges.langgraph._pauses import read_pauses
from ext_r2c.core import Answer, AnswerEvent, Approval, Ask, Done, Driver, Error, Question, RunInput, UsageEvent

from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import DEPLOY, NOTICE, memory_saver, restart, run, sqlite_saver, suite_graph, wrap
from test_langgraph_approvals import (
    MODES,
    THREAD,
    World,
    allow,
    notice_then_deploy,
    one_deploy,
    pause_at,
    world,
)


async def _requests(w: World) -> list[Approval | Question]:
    """The requests the thread holds, in the order they are asked."""
    return [p.request for p in read_pauses(await w.state(), w.source._tools)]


def _names(requests: list[Approval | Question]) -> list[str | None]:
    return [r.subject.name if isinstance(r, Approval) else None for r in requests]


# --- one gated call --------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_another_process_answers_a_gated_call_and_its_tool_runs_once(mode: str, tmp_path: Path) -> None:
    path = tmp_path / "pause.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(one_deploy, mode, saver=saver_a)
            _, first = await pause_at(a)
            assert isinstance(first, Approval)
            before = await _requests(a)
            assert not a.runs, "nothing ran before the answer"
            runs, calls = a.runs, a.calls
            asked = calls.n

        async with restart(path) as saver_b:
            b = world(one_deploy, mode, saver=saver_b, runs=runs, calls=calls)
            assert [r.id for r in await _requests(b)] == [r.id for r in before] == [first.id], (
                "the request id is the same after the restart (FR-015)"
            )
            events = [e async for e in Driver(b.source).resume(THREAD, first, allow(first))]
            assert isinstance(events[0], AnswerEvent) and isinstance(events[-1], Done), events
            assert "deployed 1.2 to north" in reply_text(events), "the rest of the work ran, and was said"
            assert [e for e in events if isinstance(e, UsageEvent)], "the turn's usage comes at its end"
            assert runs == Counter({DEPLOY: 1}), "the tool ran once, in the process that was answered"
            assert calls.n == asked + 1, "and the model was called once more, for the closing words"

    run(go())


# --- parallel and batched approvals ---------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_asks_come_in_the_same_order_and_with_the_same_ids_after_a_restart(mode: str, tmp_path: Path) -> None:
    path = tmp_path / "order.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(notice_then_deploy, mode, saver=saver_a)
            _, first = await pause_at(a)
            before = await _requests(a)
            assert _names(before) == [NOTICE, DEPLOY] and first.id == before[0].id
            runs, calls = a.runs, a.calls

        async with restart(path) as saver_b:
            b = world(notice_then_deploy, mode, saver=saver_b, runs=runs, calls=calls)
            after = await _requests(b)
            assert [r.id for r in after] == [r.id for r in before], "the same ids, in the same order"
            assert _names(after) == [NOTICE, DEPLOY]

            resumed = Driver(b.source).resume(THREAD, first, allow(first))
            await until_pause(resumed)
            assert isinstance(resumed.pending, Approval) and resumed.pending.id == before[1].id, "then the second call"
            await resumed.deliver(allow(resumed.pending))
            tail = await rest(resumed)
            assert isinstance(tail[-1], Done)
            assert runs == Counter({NOTICE: 1, DEPLOY: 1}), "each tool body ran once"

    run(go())


def test_a_per_call_answer_for_the_second_call_after_a_restart_resumes_only_that_call(tmp_path: Path) -> None:
    """A door that kept both requests may be answered for the second one first: the id says which."""
    path = tmp_path / "second.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(notice_then_deploy, "per_call", saver=saver_a)
            await pause_at(a)
            first, second = await _requests(a)
            runs, calls = a.runs, a.calls

        async with restart(path) as saver_b:
            b = world(notice_then_deploy, "per_call", saver=saver_b, runs=runs, calls=calls)
            assert isinstance(second, Approval)
            resumed = Driver(b.source).resume(THREAD, second, allow(second))
            await until_pause(resumed)
            assert isinstance(resumed.pending, Approval) and resumed.pending.id == first.id, "the first is still asked"
            assert runs == Counter({DEPLOY: 1}), "only the call that was answered ran"
            await resumed.deliver(allow(resumed.pending))
            assert isinstance((await rest(resumed))[-1], Done)
            assert runs == Counter({NOTICE: 1, DEPLOY: 1})

    run(go())


def test_a_batch_with_its_first_call_answered_is_asked_again_from_its_first_call_after_a_restart(tmp_path: Path) -> None:
    """The decisions of a half-answered batch lived in the first process's memory (FR-019)."""
    path = tmp_path / "batch.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(notice_then_deploy, "batched", saver=saver_a)
            live, first = await pause_at(a)
            assert isinstance(first, Approval)
            await live.deliver(allow(first))
            await until_pause(live)
            second = live.pending
            assert isinstance(second, Approval) and second.subject.name == DEPLOY
            assert not a.runs, "a batch runs nothing until every call is decided"
            runs, calls = a.runs, a.calls
            asked = calls.n

        async with restart(path) as saver_b:
            b = world(notice_then_deploy, "batched", saver=saver_b, runs=runs, calls=calls)
            resumed = Driver(b.source).resume(THREAD, second, allow(second))
            out = await until_pause(resumed)
            assert isinstance(out[-1], Ask) and out[-1].request.id == first.id, (
                "the first call is asked again: its answer was in memory that is gone"
            )
            assert not runs and calls.n == asked, "and nothing ran, and the model was not called"
            await resumed.deliver(allow(first))
            tail = await rest(resumed)
            assert isinstance(tail[-1], Done)
            assert runs == Counter({NOTICE: 1, DEPLOY: 1}), "each tool body ran once"

    run(go())


# --- a hand-written interrupt ---------------------------------------------------------------------


def test_another_process_answers_a_question_the_graph_wrote_itself(tmp_path: Path) -> None:
    path = tmp_path / "question.db"

    def answer_to(request: Question) -> Answer:
        return Answer.parse(
            {"kind": "answer", "id": request.id, "answered_by": {"role": "person"},
             "outcome": "answered", "value": {"title": "Q3 report"}}
        )

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            live = Driver(wrap(suite_graph(saver_a))).start(THREAD, RunInput("a report"))
            await until_pause(live)
            asked = live.pending
            assert isinstance(asked, Question)

        async with restart(path) as saver_b:
            source = wrap(suite_graph(saver_b))
            events = [e async for e in Driver(source).resume(THREAD, asked, answer_to(asked))]
            assert isinstance(events[-1], Done), events
            assert reply_text(events) == "Got: Q3 report"

    run(go())


# --- a pause that is gone --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_an_in_memory_checkpointer_holds_nothing_after_a_restart_so_the_answer_is_lost(mode: str) -> None:
    async def go() -> None:
        a = world(one_deploy, mode, saver=memory_saver())
        _, first = await pause_at(a)
        assert isinstance(first, Approval)
        asked = a.calls.n

        b = world(one_deploy, mode, saver=memory_saver(), runs=a.runs, calls=a.calls)  # a new process, a new memory
        events = [e async for e in Driver(b.source).resume(THREAD, first, allow(first))]
        assert [type(e) for e in events] == [AnswerEvent, Error], events
        error = events[-1]
        assert isinstance(error, Error) and error.code == "lost" and "lost" in error.reason.lower(), error
        assert a.calls.n == asked and not a.runs, "the graph was not started"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_an_answer_already_applied_is_lost_the_second_time_and_the_graph_is_not_started(mode: str, tmp_path: Path) -> None:
    path = tmp_path / "twice.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(one_deploy, mode, saver=saver_a)
            _, first = await pause_at(a)
            assert isinstance(first, Approval)
            runs, calls = a.runs, a.calls

        async with restart(path) as saver_b:
            b = world(one_deploy, mode, saver=saver_b, runs=runs, calls=calls)
            done = [e async for e in Driver(b.source).resume(THREAD, first, allow(first))]
            assert isinstance(done[-1], Done)
            asked = calls.n

            again = [e async for e in Driver(b.source).resume(THREAD, first, allow(first))]
            assert [type(e) for e in again] == [AnswerEvent, Error], again
            assert isinstance(again[-1], Error) and again[-1].code == "lost"
            assert runs == Counter({DEPLOY: 1}) and calls.n == asked, "nothing ran a second time"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_thread_that_was_pruned_is_lost_and_the_graph_is_not_started(mode: str, tmp_path: Path) -> None:
    path = tmp_path / "pruned.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(one_deploy, mode, saver=saver_a)
            _, first = await pause_at(a)
            assert isinstance(first, Approval)
            runs, calls = a.runs, a.calls
            asked = calls.n

        async with restart(path) as saver_b:
            b = world(one_deploy, mode, saver=saver_b, runs=runs, calls=calls)
            await saver_b.adelete_thread(THREAD)  # the operator's clean-up of old threads
            events = [e async for e in Driver(b.source).resume(THREAD, first, allow(first))]
            assert [type(e) for e in events] == [AnswerEvent, Error], events
            error = events[-1]
            assert isinstance(error, Error) and error.code == "lost", error
            assert not runs and calls.n == asked, "the graph was not started"

    run(go())
