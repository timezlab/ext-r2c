"""Other ways a graph asks: a hand-written `interrupt()`, in one node or in parallel nodes (spec 006,
story 5; R8, R14; FR-014, FR-021; SC-006; pause-mapping rows 4 to 7, 9 and 10).

Real graphs, a real checkpointer and the real `Driver`; the only fake is the scripted model of the
tool-calling tests. Everything a graph writes in `interrupt(...)` here is invented (constitution VI).

The graph's side is read from what `interrupt()` *returned* (`seen`): that is what the graph gets back,
and the tests never look at the bridge's insides to learn it.
"""

from __future__ import annotations

import json
import operator
import re
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from typing_extensions import TypedDict

import ext_r2c.bridges.langgraph as bridge
from ext_r2c.bridges.langgraph._pauses import read_pauses
from ext_r2c.core import Approval, Done, Driver, Error, Question, RunInput

from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import agent, memory_saver, restart, run, sqlite_saver, wrap
from langgraph_models import Call, Say, Scripted, Turn, tool_results
from test_langgraph_approvals import (
    CONFIG,
    MODES,
    THREAD,
    _answer,
    _per_call_interrupt,
    _state_of,
    declined,
    notice_then_deploy,
    world,
)

NEEDS_INPUT = "The agent needs input"

QUESTION: dict[str, Any] = {
    "kind": "question", "id": "q-region", "title": "Which region?", "answer_by": {"role": "person"},
    "fields": [{"key": "region", "header": "Region", "text": "The region to roll out to", "type": "text"}],
}


def approval(role: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "approval", "id": "ap-9", "title": "Publish the page", "answer_by": role,
        "subject": {"type": "tool_call", "name": "publish_page", "args": {"slug": "intro"}},
        "decisions": ["allow", "deny"],
    }


# --- a graph whose tool body asks -----------------------------------------------------------------


def asker(*payloads: Any) -> tuple[Any, dict[int, Any]]:
    """An agent whose one tool calls `interrupt()` once for each payload, in order, and says what each
    returned. `seen` maps a payload's index to what its call returned: a payload still waiting for its answer
    is not in it. (The body starts again at each resume and the calls before replay their answers, so what a
    call returned is kept by index, not appended.)"""
    seen: dict[int, Any] = {}

    @tool("ask_it")
    def ask_it() -> str:
        """Ask the caller something."""
        for index, payload in enumerate(payloads):
            seen[index] = interrupt(payload)
        return "got " + " + ".join(repr(seen[index]) for index in range(len(payloads)))

    def script(messages: list[BaseMessage]) -> Turn:
        return Say(str(tool_results(messages)[-1].content)) if tool_results(messages) else Call(("ask_it", {}))

    graph = agent(Scripted(script=script), [ask_it], memory_saver(), name="asker")
    return wrap(graph), seen


async def ask(source: Any) -> tuple[Any, Question | Approval]:
    """Start a run and read it up to its ask."""
    live = Driver(source).start(THREAD, RunInput("go"))
    await until_pause(live)
    assert live.pending is not None, "the run was expected to ask"
    return live, live.pending


async def finish(live: Any, request: Question | Approval, value: dict[str, Any] | None) -> list[Any]:
    """Answer the pending request and read the run to its end."""
    await live.deliver(_answer(request, value))
    return await rest(live)


# --- 1. a valid R2C request is asked as it is -------------------------------------------------------


def test_a_valid_question_is_asked_as_it_is_and_the_graph_gets_the_answers_value() -> None:
    source, seen = asker(QUESTION)

    async def go() -> None:
        live, asked = await ask(source)
        assert isinstance(asked, Question) and asked.id == "q-region", "its own id, not one the bridge made"
        assert asked.title == "Which region?" and asked.answer_by.role == "person"
        assert [f.key for f in asked.fields] == ["region"]
        tail = await finish(live, asked, {"region": "north"})
        assert isinstance(tail[-1], Done)
        assert seen == {0: {"region": "north"}}, "interrupt() returns the answer's value mapping"
        assert "got {'region': 'north'}" in reply_text(tail)

    run(go())


@pytest.mark.parametrize("role", [{"role": "person"}, {"role": "approver", "approver_role": "release-manager"}])
def test_a_valid_approval_for_a_person_or_an_approver_is_asked_as_it_is(role: dict[str, str]) -> None:
    source, seen = asker(approval(role))

    async def go() -> None:
        live, asked = await ask(source)
        assert isinstance(asked, Approval) and asked.id == "ap-9" and asked.answer_by.role == role["role"]
        tail = await finish(live, asked, {"decision": "deny", "reason": "not today"})
        assert isinstance(tail[-1], Done)
        assert seen == {0: {"decision": "deny", "reason": "not today"}}, "the decision mapping, as it was given"

    run(go())


# --- 2. anything else falls back to a question for a person -----------------------------------------------


def test_a_string_is_asked_as_a_question_for_a_person_with_one_text_field() -> None:
    source, seen = asker("Which region?")

    async def go() -> None:
        live, asked = await ask(source)
        assert isinstance(asked, Question) and asked.answer_by.role == "person"
        assert asked.title == "Which region?" and asked.description is None
        assert [(f.key, f.type) for f in asked.fields] == [("answer", "text")]
        assert asked.id.startswith("lg-"), "an id the bridge made from the interrupt's"
        tail = await finish(live, asked, {"answer": "north"})
        assert isinstance(tail[-1], Done)
        assert seen == {0: "north"}, "the graph gets the answered text, not a mapping"
        assert "got 'north'" in reply_text(tail)

    run(go())


@pytest.mark.parametrize(
    ("payload", "title"),
    [("x" * 250, "x" * 200), ("y" * 200, "y" * 200), ("", NEEDS_INPUT)],
    ids=["cut at 200", "exactly 200 is kept", "empty"],
)
def test_a_strings_title_is_cut_at_200_characters_and_an_empty_one_is_replaced(payload: str, title: str) -> None:
    source, _ = asker(payload)

    async def go() -> None:
        _, asked = await ask(source)
        assert asked.title == title

    run(go())


@pytest.mark.parametrize(
    "payload",
    [{"region": "north", "tags": [1, 2]}, ["a", "b"], 42, None, {"when": date(2026, 11, 22)}],
    ids=["a mapping that is not R2C", "a list", "a number", "None", "something json cannot write"],
)
def test_any_other_value_is_a_question_whose_description_shows_it_as_json(payload: Any) -> None:
    source, seen = asker(payload)

    async def go() -> None:
        live, asked = await ask(source)
        assert isinstance(asked, Question) and asked.answer_by.role == "person"
        assert asked.title == NEEDS_INPUT
        assert asked.description is not None
        assert json.loads(asked.description) == json.loads(json.dumps(payload, default=str))
        await finish(live, asked, {"answer": "ok"})
        assert seen == {0: "ok"}

    run(go())


def test_the_description_of_a_long_string_is_the_whole_text_cut_at_2000_characters() -> None:
    source, _ = asker("v" * 2500)

    async def go() -> None:
        _, asked = await ask(source)
        assert asked.title == "v" * 200 and asked.description == "v" * 2000

    run(go())


def test_the_description_of_a_large_value_is_cut_at_2000_characters() -> None:
    source, _ = asker(list(range(2000)))

    async def go() -> None:
        _, asked = await ask(source)
        assert asked.description is not None and len(asked.description) == 2000

    run(go())


@pytest.mark.parametrize("payload", ["Which region?", QUESTION, ["a"]], ids=["fallback", "own question", "other value"])
def test_a_declined_question_resumes_the_graph_with_none(payload: Any) -> None:
    source, seen = asker(payload)

    async def go() -> None:
        live, asked = await ask(source)
        await live.deliver(declined(asked))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        assert seen == {0: None}, "declined: the graph's own `no answer`"

    run(go())


def test_a_mapping_that_looks_like_a_question_but_is_not_valid_is_a_fallback() -> None:
    broken = {"kind": "question", "id": "q-1", "title": "Which region?"}  # no `answer_by`, no fields
    source, _ = asker(broken)

    async def go() -> None:
        _, asked = await ask(source)
        assert asked.title == NEEDS_INPUT and asked.id != "q-1" and asked.id.startswith("lg-")
        assert asked.description is not None and json.loads(asked.description) == broken

    run(go())


# --- 3. an approval addressed to the caller is never asked as one (V) --------------------------------------


def test_an_approval_addressed_to_the_caller_falls_back_to_a_question_for_a_person() -> None:
    source, seen = asker(approval({"role": "caller"}))

    async def go() -> None:
        live, asked = await ask(source)
        assert isinstance(asked, Question), "never an Approval: only a person or an approver answers one"
        assert asked.answer_by.role == "person" and asked.title == NEEDS_INPUT
        assert [(f.key, f.type) for f in asked.fields] == [("answer", "text")]
        assert asked.description is not None and json.loads(asked.description)["id"] == "ap-9", "it shows what was asked"
        tail = await finish(live, asked, {"answer": "yes, publish"})
        assert isinstance(tail[-1], Done)
        assert seen == {0: "yes, publish"}

    run(go())


# --- 4. several interrupts in one node, one after the other -------------------------------------------------


def test_interrupts_in_a_row_in_one_node_are_asked_and_answered_in_order() -> None:
    source, seen = asker("First?", "Second?")

    async def go() -> None:
        live, first = await ask(source)
        assert first.title == "First?"
        await live.deliver(_answer(first, {"answer": "x"}))
        await until_pause(live)
        second = live.pending
        assert second is not None and second.title == "Second?" and second.id != first.id
        assert seen == {0: "x"}, "the second was not asked before the first was answered"
        tail = await finish(live, second, {"answer": "y"})
        assert isinstance(tail[-1], Done)
        assert seen == {0: "x", 1: "y"} and "got 'x' + 'y'" in reply_text(tail)

    run(go())


# --- 5. several interrupts at once, in parallel nodes --------------------------------------------------------


class Fanned(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    log: Annotated[list[str], operator.add]


def _question(id: str) -> dict[str, Any]:
    return {**QUESTION, "id": id, "title": f"Question {id}", "fields": [{**QUESTION["fields"][0], "key": "v"}]}


def _node(name: str, payload: Any, done: list[str], starts: Counter[str]) -> Any:
    def node(state: Fanned) -> dict[str, Any]:
        starts[name] += 1
        answer = interrupt(payload)
        done.append(name)
        return {"log": [f"{name}:{answer['v']}"]}

    return node


class Fan:
    """Parallel nodes that each ask one question of their own, over a checkpointer."""

    def __init__(self, payloads: dict[str, Any], saver: Any, done: list[str] | None = None, starts: Counter[str] | None = None):
        self.done = [] if done is None else done
        self.starts: Counter[str] = Counter() if starts is None else starts
        builder = StateGraph(Fanned)
        for name, payload in payloads.items():
            builder.add_node(name, _node(name, payload, self.done, self.starts))
            builder.add_edge(START, name)
            builder.add_edge(name, END)
        self.graph = builder.compile(checkpointer=saver)
        self.source = wrap(self.graph)

    async def requests(self) -> list[Question | Approval]:
        return [p.request for p in read_pauses(await self.graph.aget_state(CONFIG))]

    async def log(self) -> list[str]:
        return list((await self.graph.aget_state(CONFIG)).values.get("log", []))


ABC = {"a": _question("q-a"), "b": _question("q-b"), "c": _question("q-c")}


def test_parallel_interrupts_are_asked_one_at_a_time_in_the_order_the_graph_lists_them() -> None:
    fan = Fan(ABC, memory_saver())

    async def go() -> None:
        live = Driver(fan.source).start(THREAD, RunInput("go"))
        asked: list[str] = []
        await until_pause(live)
        while live.pending is not None:
            request = live.pending
            asked.append(request.id)
            assert [r.id for r in await fan.requests()] == ["q-a", "q-b", "q-c"][len(asked) - 1 :], (
                "the ones not answered yet are all still pending in the graph"
            )
            await live.deliver(_answer(request, {"v": request.id[-1].upper()}))
            await until_pause(live)
        assert asked == ["q-a", "q-b", "q-c"]
        assert sorted(await fan.log()) == ["a:A", "b:B", "c:C"]

    run(go())


def test_an_answer_resumes_only_its_own_interrupt_by_id() -> None:
    fan = Fan(ABC, memory_saver())

    async def go() -> None:
        live = Driver(fan.source).start(THREAD, RunInput("go"))
        await until_pause(live)
        a, b, c = await fan.requests()
        assert live.pending is not None and live.pending.id == a.id
        await live.cancel()

        # The third, answered first: only its node goes on; the others ask again and stay pending.
        again = Driver(fan.source).resume(THREAD, c, _answer(c, {"v": "C"}))
        await until_pause(again)
        assert fan.done == ["c"], "only the node whose interrupt was answered went past it"
        assert [r.id for r in await fan.requests()] == [a.id, b.id]
        assert again.pending is not None and again.pending.id == a.id, "and the first still in order is asked next"
        await again.cancel()

    run(go())


def test_two_requests_with_the_same_own_id_are_not_told_apart_and_the_first_in_order_matches() -> None:
    """Pinned (and named in the contract): an author keeps the ids of requests that wait together distinct."""
    fan = Fan({"a": _question("q-x"), "b": _question("q-x")}, memory_saver())

    async def go() -> None:
        live = Driver(fan.source).start(THREAD, RunInput("go"))
        await until_pause(live)
        asked = live.pending
        assert asked is not None and asked.id == "q-x"
        await live.deliver(_answer(asked, {"v": "A"}))
        await until_pause(live)
        assert fan.done == ["a"], "the answer went to the first, in the order the graph lists them"
        assert live.pending is not None and live.pending.id == "q-x", "the second is asked next, under the same id"
        await live.cancel()

    run(go())


def test_parallel_interrupts_come_in_the_same_order_after_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "fan.db"

    async def go() -> None:
        done: list[str] = []
        async with sqlite_saver(path) as saver_a:
            a = Fan(ABC, saver_a, done)
            live = Driver(a.source).start(THREAD, RunInput("go"))
            await until_pause(live)
            before = [r.id for r in await a.requests()]
            await live.cancel()

        async with restart(path) as saver_b:
            b = Fan(ABC, saver_b, done)
            requests = await b.requests()
            assert [r.id for r in requests] == before == ["q-a", "q-b", "q-c"], "the same order, the same ids"
            resumed = Driver(b.source).resume(THREAD, requests[0], _answer(requests[0], {"v": "A"}))
            events = await until_pause(resumed)
            for expected in ("q-b", "q-c"):
                assert resumed.pending is not None and resumed.pending.id == expected
                await resumed.deliver(_answer(resumed.pending, {"v": expected[-1].upper()}))
                events = await until_pause(resumed)
            assert isinstance(events[-1], Done), events
            assert sorted(await b.log()) == ["a:A", "b:B", "c:C"]

    run(go())


def test_a_fallback_question_comes_after_the_tool_approvals() -> None:
    state = _state_of(
        [
            SimpleNamespace(id="i-text", value="Which region?", response_schema=None),
            _per_call_interrupt("i-call", "c1", "send_notice"),
        ],
        [("c1", "send_notice")],
    )
    first, second = read_pauses(state)
    assert [first.request.id, second.request.id] == ["lg-i-call", "lg-i-text"]
    assert isinstance(first.request, Approval) and isinstance(second.request, Question)


# --- 6. SC-006: no approval is for the caller, and nothing in the bridge answers one -------------------------


async def _every_ask(live: Any, answer: Any) -> tuple[list[Question | Approval], list[Any]]:
    """Read a run to its end, answering every ask with `answer(request)`; the asks and all the events."""
    asks: list[Question | Approval] = []
    events: list[Any] = await until_pause(live)
    while live.pending is not None:
        asks.append(live.pending)
        await live.deliver(answer(live.pending))
        events += await until_pause(live)
    return asks, events


def _allow(request: Question | Approval) -> Any:
    if isinstance(request, Approval):
        return _answer(request, {"decision": "allow"})
    return _answer(request, {request.fields[0].key: "ok"})


def test_no_path_that_yields_an_approval_addresses_it_to_the_caller() -> None:
    """The walk of SC-006: the middleware in both modes, a hand-written approval for a person and for an
    approver, and the one addressed to the caller."""

    async def go() -> None:
        walked: dict[str, list[Question | Approval]] = {}
        for mode in MODES:
            w = world(notice_then_deploy, mode)
            walked[mode], _ = await _every_ask(Driver(w.source).start(THREAD, RunInput("go")), _allow)
        for label, payload in (
            ("person", approval({"role": "person"})),
            ("approver", approval({"role": "approver", "approver_role": "release-manager"})),
            ("caller", approval({"role": "caller"})),
        ):
            source, _ = asker(payload)
            walked[label], _ = await _every_ask(Driver(source).start(THREAD, RunInput("go")), _allow)

        for label, asks in walked.items():
            assert asks, f"{label}: the run asked nothing"
            for request in asks:
                if isinstance(request, Approval):
                    assert request.answer_by.role in ("person", "approver"), f"{label}: an approval for the caller"
        assert all(isinstance(r, Approval) for r in walked["per_call"] + walked["batched"] + walked["person"] + walked["approver"])
        assert all(isinstance(r, Question) for r in walked["caller"]), "the caller's one is a question for a person"

    run(go())


def test_nothing_in_the_bridge_builds_an_answer() -> None:
    """An approval is answered by a human or a policy, never by a model (V): the bridge is not the
    one that answers, so it has no `Answer(...)` and no `AnswerEvent(...)` to give."""
    folder = Path(bridge.__file__).parent
    builds = re.compile(r"\bAnswer(Event)?\(")
    found = [p.name for p in folder.glob("*.py") if builds.search(p.read_text())]
    assert found == [], found


@pytest.mark.parametrize("mode", MODES)
def test_the_run_never_yields_an_answer_of_its_own(mode: str) -> None:
    """A source that yielded an `AnswerEvent` would end the run `protocol`: every path here ends `done`."""
    w = world(notice_then_deploy, mode)

    async def go() -> None:
        live = Driver(w.source).start(THREAD, RunInput("go"))
        asks, events = await _every_ask(live, _allow)
        events += await rest(live)
        assert isinstance(events[-1], Done) and not [e for e in events if isinstance(e, Error)]
        assert len(asks) == 2

    run(go())
