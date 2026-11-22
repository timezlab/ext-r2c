"""A batch in progress (spec 006, R10, D8; FR-019).

`HumanInTheLoopMiddleware` in `batched` mode wants every decision of a turn in one resume, and the
graph's state has no place for half of them. The agent keeps the decisions given so far in memory, asks
the next call, and sends the whole set once it is complete. The first part pins the small map
(`_batch`) with no graph; the second part pins what the caller and the graph see.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from langgraph.types import Command

from ext_r2c.bridges.langgraph._batch import LIMIT, Batch, Batches
from ext_r2c.bridges.langgraph._pauses import read_pauses
from ext_r2c.core import AnswerEvent, Approval, Ask, Done, Driver, Error, RunInput

from agent_source_suite import rest, until_pause
from langgraph_graphs import DEPLOY, NOTICE, run
from test_langgraph_approvals import THREAD, World, allow, deny, notice_then_deploy, pause_at, tool_message, world

APPROVE = {"type": "approve"}


# --- 1. the map ---------------------------------------------------------------------------------------


def test_a_batch_knows_what_is_decided_and_what_comes_next() -> None:
    batch = Batch(size=3)
    assert not batch.complete() and batch.next_open() == 0
    batch.decide(1, {"type": "reject", "message": "no"})
    assert batch.next_open() == 0, "the first call with no decision, not the next one after the last"
    batch.decide(0, APPROVE)
    assert batch.next_open() == 2 and not batch.complete()
    batch.decide(2, APPROVE)
    assert batch.complete() and batch.next_open() is None


def test_the_decisions_leave_in_position_order_whatever_order_they_came_in() -> None:
    batch = Batch(size=3)
    for position, kind in ((2, "c"), (0, "a"), (1, "b")):
        batch.decide(position, {"type": "reject", "message": kind})
    assert [d["message"] for d in batch.ordered()] == ["a", "b", "c"]


def test_an_incomplete_batch_cannot_be_sent() -> None:
    batch = Batch(size=2)
    batch.decide(0, APPROVE)
    with pytest.raises(ValueError, match="1 of 2"):
        batch.ordered()


def test_a_position_outside_the_batch_is_refused() -> None:
    batch = Batch(size=2)
    for bad in (-1, 2):
        with pytest.raises(ValueError, match="position"):
            batch.decide(bad, APPROVE)


def test_a_second_decision_for_a_position_is_refused_and_the_first_stands() -> None:
    batch = Batch(size=1)
    batch.decide(0, {"type": "reject"})
    with pytest.raises(ValueError, match="already"):
        batch.decide(0, APPROVE)
    assert batch.ordered() == [{"type": "reject"}]


def test_the_map_is_keyed_by_thread_and_interrupt() -> None:
    batches = Batches()
    one = batches.record("t-1", "i-1", size=2, position=0, decision=APPROVE)
    assert batches.record("t-1", "i-1", size=2, position=1, decision=APPROVE) is one, "the same batch goes on"
    assert one.complete()
    assert batches.get("t-1", "i-1") is one
    assert batches.get("t-2", "i-1") is None and batches.get("t-1", "i-2") is None
    assert len(batches) == 1


def test_a_record_with_another_size_starts_the_batch_again() -> None:
    batches = Batches()
    batches.record("t", "i", size=2, position=0, decision=APPROVE)
    again = batches.record("t", "i", size=3, position=1, decision=APPROVE)
    assert again.size == 3 and list(again.decisions) == [1]


def test_the_map_keeps_at_most_1024_records_and_drops_the_oldest_first() -> None:
    assert LIMIT == 1024
    batches = Batches()
    for n in range(LIMIT + 1):
        batches.record("t", f"i-{n}", size=2, position=0, decision=APPROVE)
    assert len(batches) == LIMIT
    assert batches.get("t", "i-0") is None, "the oldest was dropped"
    assert batches.get("t", "i-1") is not None and batches.get("t", f"i-{LIMIT}") is not None


def test_a_record_is_dropped_alone_or_with_its_thread_or_when_its_interrupt_is_gone() -> None:
    batches = Batches()
    for thread, interrupt in (("t-1", "i-1"), ("t-1", "i-2"), ("t-1", "i-3"), ("t-2", "i-1")):
        batches.record(thread, interrupt, size=2, position=0, decision=APPROVE)
    batches.drop("t-1", "i-1")
    batches.drop("t-1", "i-1")  # dropping what is not there is nothing
    assert batches.get("t-1", "i-1") is None and len(batches) == 3
    batches.prune("t-1", alive=["i-2"])
    assert batches.get("t-1", "i-2") is not None and batches.get("t-1", "i-3") is None
    assert batches.get("t-2", "i-1") is not None, "another thread is not touched"
    batches.drop_thread("t-1")
    assert len(batches) == 1 and batches.get("t-2", "i-1") is not None


# --- 2. behaviour -----------------------------------------------------------------------------------------


class Sent:
    """What went into the graph's `astream`, in order: a spy over the real call."""

    def __init__(self, w: World) -> None:
        self.inputs: list[Any] = []
        real = w.graph.astream

        async def astream(graph_input: Any, *args: Any, **kwargs: Any) -> Any:
            self.inputs.append(graph_input)
            async for part in real(graph_input, *args, **kwargs):
                yield part

        w.graph.astream = astream

    @property
    def resumes(self) -> list[Any]:
        return [i.resume for i in self.inputs if isinstance(i, Command)]


def test_the_first_answer_of_a_batch_is_recorded_and_the_next_call_is_asked_with_no_graph_call() -> None:
    w = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        (pending,) = (await w.state()).interrupts
        before, asked, sent = await w.state(), w.calls.n, Sent(w)

        await live.deliver(allow(first))
        events = await until_pause(live)
        second = live.pending
        assert [type(e) for e in events] == [AnswerEvent, Ask], "the next call is asked and nothing else happens"
        assert isinstance(second, Approval) and second.subject.name == DEPLOY
        assert second.id == f"lg-{pending.id}-1"
        assert not sent.inputs and w.calls.n == asked, "the graph was not called"
        assert (await w.state()).config == before.config, "and wrote nothing"
        batch = w.source._batches.get(THREAD, pending.id)
        assert batch is not None and batch.decisions == {0: APPROVE}

    run(go())


def test_the_last_answer_sends_every_decision_in_one_resume_in_position_order() -> None:
    w = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        (pending,) = (await w.state()).interrupts
        sent = Sent(w)
        await live.deliver(allow(first))
        await until_pause(live)
        assert isinstance(live.pending, Approval)
        await live.deliver(deny(live.pending, "Not before Monday."))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        decisions = [APPROVE, {"type": "reject", "message": "Not before Monday."}]
        assert sent.resumes == [{pending.id: {"decisions": decisions}}], "one resume, once the batch was complete"
        assert not len(w.source._batches), "and the record is gone"
        assert w.runs == Counter({NOTICE: 1})

    run(go())


def test_answers_that_come_out_of_order_still_leave_in_position_order() -> None:
    w = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        _, second = await _both(w, first)
        sent = Sent(w)
        # The second call's answer arrives first (a caller that kept both requests); then the first's.
        resumed = Driver(w.source).resume(THREAD, second, deny(second, "no"))
        out = await until_pause(resumed)  # a run that asked stays open until it is answered
        assert [type(e) for e in out] == [AnswerEvent, Ask] and isinstance(out[-1], Ask)
        assert out[-1].request.id == first.id, "the first call has no decision yet: it is asked"
        assert not sent.inputs
        await resumed.deliver(allow(first))
        tail = await rest(resumed)
        assert isinstance(tail[-1], Done)
        assert [list(r.values()) for r in sent.resumes] == [[{"decisions": [APPROVE, {"type": "reject", "message": "no"}]}]]

    run(go())


async def _both(w: World, first: Approval) -> tuple[Approval, Approval]:
    """The two requests of the batch, as the doors would have kept them."""
    state = await w.state()
    a, b = (p.request for p in read_pauses(state, w.source._tools))
    assert isinstance(a, Approval) and isinstance(b, Approval) and a.id == first.id
    return a, b


def test_an_answer_for_a_call_the_agent_has_no_record_of_is_kept_and_the_batch_starts_from_its_first_call() -> None:
    """A restart in the middle: the new agent shares the checkpointer and none of the old one's memory."""
    old = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(old)
        assert isinstance(first, Approval)
        _, second = await _both(old, first)
        new = world(notice_then_deploy, "batched", saver=old.saver)
        sent = Sent(new)

        resumed = Driver(new.source).resume(THREAD, second, allow(second))
        events = await until_pause(resumed)  # a run that asked stays open until it is answered
        assert [type(e) for e in events] == [AnswerEvent, Ask]
        assert events[-1].request.id == first.id, "the batch is asked again from its first call"  # type: ignore[union-attr]
        assert not sent.inputs and not new.calls.n, "no graph call for an answer that only completes half"
        (pending,) = (await new.state()).interrupts
        kept = new.source._batches.get(THREAD, pending.id)
        assert kept is not None and kept.decisions == {1: APPROVE}, "the answer already given is kept"

        await resumed.deliver(allow(first))
        tail = await rest(resumed)
        assert isinstance(tail[-1], Done)
        assert new.runs == Counter({NOTICE: 1, DEPLOY: 1}) and not len(new.source._batches)

    run(go())


def test_a_second_answer_for_a_call_already_decided_is_refused_and_the_first_decision_stands() -> None:
    """A replayed or changed answer must not turn an approval into a denial or back (outside review, R19 S4).
    With `per_call` an answered request is gone from the thread; here it stays in the checkpoint until the
    batch is complete, so the agent is the one that refuses it."""
    w = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        _, second = await _both(w, first)
        await live.deliver(allow(first))
        await until_pause(live)  # the second call is asked now
        (pending,) = (await w.state()).interrupts
        sent = Sent(w)

        out = [e async for e in Driver(w.source).resume(THREAD, first, deny(first, "changed my mind"))]
        assert isinstance(out[-1], Error) and out[-1].code == "lost", out
        kept = w.source._batches.get(THREAD, pending.id)
        assert kept is not None and kept.decisions == {0: APPROVE}, "the first decision stands"
        assert not sent.inputs, "and the graph was not called"

        await live.deliver(allow(second))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        assert [list(r.values()) for r in sent.resumes] == [[{"decisions": [APPROVE, APPROVE]}]]

    run(go())


def test_the_record_is_dropped_when_its_pause_is_found_lost() -> None:
    w = world(notice_then_deploy, "batched")

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        _, second = await _both(w, first)
        await live.deliver(allow(first))
        await until_pause(live)
        assert len(w.source._batches) == 1

        await w.saver.adelete_thread(THREAD)  # the checkpointer no longer holds the thread
        out = [e async for e in Driver(w.source).resume(THREAD, second, allow(second))]
        assert isinstance(out[-1], Error) and out[-1].code == "lost"
        assert not len(w.source._batches), "nothing is left of the batch"

    run(go())


def test_two_threads_keep_their_own_batches() -> None:
    w = world(notice_then_deploy, "batched")
    other = THREAD + "-other"

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        other_live = Driver(w.source).start(other, RunInput("go"))
        await until_pause(other_live)
        assert isinstance(other_live.pending, Approval)
        await live.deliver(allow(first))
        await until_pause(live)
        assert len(w.source._batches) == 1, "only the thread that answered has a record"
        await other_live.deliver(allow(other_live.pending))
        await until_pause(other_live)
        assert len(w.source._batches) == 2
        assert isinstance(live.pending, Approval)
        await live.deliver(allow(live.pending))
        tail = await rest(live)
        assert isinstance(tail[-1], Done) and len(w.source._batches) == 1, "the other thread's batch is still open"
        assert w.runs == Counter({NOTICE: 1, DEPLOY: 1})
        assert tool_message(await w.messages(), "call-0-1").status != "error"

    run(go())
