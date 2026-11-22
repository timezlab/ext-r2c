"""A turn that ends `input_required` (spec 006, story 5; R12; FR-022; D10; pause-mapping row 8; plan
points 1 and 4).

Real `create_agent` graphs with a real `response_format` (`ToolStrategy` and `ProviderStrategy`), a real
checkpointer and the real `Driver`; the model is scripted. The answer to the question is a new human
message of the same thread, never a resume, so these tests read the graph's history to tell the two apart.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel
from typing_extensions import TypedDict  # LangChain and pydantic refuse `typing.TypedDict` before Python 3.12

from ext_r2c.bridges.langgraph._reply import Reply
from ext_r2c.core import AnswerEvent, Ask, Done, Driver, Error, Question, ReplyChunk, RunInput, UsageEvent

from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import NOTICE, agent, counted_tools, memory_saver, restart, run, sqlite_saver, wrap
from langgraph_models import Call, Calls, Gate, Say, Scripted, Turn, humans, last_human, tool_results
from test_langgraph_approvals import CONFIG, THREAD, _answer, declined

Status = Literal["input_required", "completed", "error"]


class Result(BaseModel):
    status: Status
    message: str


class Kind(Enum):  # not a `str` Enum: its members do not compare equal to the text, so only its value reads
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"


class WithEnum(BaseModel):
    status: Kind
    message: str


@dataclass
class AsDataclass:
    status: Status
    message: str


class AsTypedDict(TypedDict):
    status: Status
    message: str


SCHEMAS = {"pydantic": Result, "enum": WithEnum, "dataclass": AsDataclass, "typed dict": AsTypedDict}

QUESTION = "Which region?"


def said(strategy: Any, status: str, message: str, *, tokens: tuple[int, int] | None = (6, 2)) -> Turn:
    """What a model does to end a turn with a structured reply: under `ToolStrategy` a call of the schema's
    own tool, under `ProviderStrategy` the JSON as its text."""
    payload = {"status": status, "message": message}
    if isinstance(strategy, ToolStrategy):
        return Call((strategy.schema.__name__, payload), tokens=tokens)
    return Say(json.dumps(payload), tokens=tokens)


def regions(strategy: Any) -> Any:
    """Ask which region, then, once a second human message answers, finish."""

    def script(messages: list[BaseMessage]) -> Turn:
        if humans(messages) == 1:
            return said(strategy, "input_required", QUESTION)
        return said(strategy, "completed", f"Rolled out to {last_human(messages)}")

    return script


def asking_graph(strategy: Any, script: Any, calls: Calls) -> Any:
    """A graph with a response format whose one tool asks the caller (`interrupt()`) before it answers."""

    @tool("ask_it")
    def ask_it() -> str:
        """Ask the caller something."""
        return f"got {interrupt('Which one?')}"

    return agent(Scripted(script=script, calls=calls), [ask_it], memory_saver(), response_format=strategy)


class Built:
    def __init__(self, script: Any, strategy: Any, saver: Any = None, calls: Calls | None = None) -> None:
        self.calls = Calls() if calls is None else calls
        self.saver = memory_saver() if saver is None else saver
        self.graph = agent(Scripted(script=script, calls=self.calls), [], self.saver, response_format=strategy)
        self.source = wrap(self.graph)

    async def messages(self) -> list[BaseMessage]:
        return list((await self.graph.aget_state(CONFIG)).values["messages"])


async def ask(source: Any, text: str = "go") -> tuple[Any, list[Any]]:
    """Start a run and read it up to its ask: the run and the events so far."""
    live = Driver(source).start(THREAD, RunInput(text))
    events = await until_pause(live)
    assert live.pending is not None, [type(e).__name__ for e in events]
    return live, events


STRATEGIES = [ToolStrategy(Result), ProviderStrategy(Result)]
IDS = ["tool", "provider"]


# --- 1. the question ------------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES, ids=IDS)
def test_a_turn_that_says_input_required_is_asked_as_a_question_for_the_caller(strategy: Any) -> None:
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, events = await ask(b.source)
        asked = live.pending
        assert isinstance(asked, Question) and isinstance(events[-1], Ask)
        assert asked.answer_by.role == "caller", "the caller's model answers it, not a person"
        assert asked.title == QUESTION and asked.description is None
        assert [(f.key, f.type) for f in asked.fields] == [("answer", "text")]
        (last_ai, *_) = [m for m in reversed(await b.messages()) if isinstance(m, AIMessage)]
        assert asked.id == f"lg-ir-{last_ai.id}", "named after the turn's last AI message"
        assert not [e for e in events if isinstance(e, ReplyChunk)], "the structured JSON is not the reply (FR-022)"
        assert isinstance(events[-2], UsageEvent) and events[-2].usage.input_tokens == 6, "usage, then the ask"
        await live.cancel()

    run(go())


@pytest.mark.parametrize("schema", list(SCHEMAS), ids=list(SCHEMAS))
def test_every_kind_of_schema_a_response_format_takes_is_read(schema: str) -> None:
    strategy = ToolStrategy(SCHEMAS[schema])
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        assert isinstance(live.pending, Question) and live.pending.title == QUESTION
        await live.cancel()

    run(go())


@pytest.mark.parametrize(
    ("message", "title", "description"),
    [
        ("Which region?", "Which region?", None),
        ("Which region?\nNorth or south, please.", "Which region?", "Which region?\nNorth or south, please."),
        ("  Which region?  ", "Which region?", None),
        ("w" * 250, "w" * 200, "w" * 250),
        ("w" * 2500, "w" * 200, "w" * 2000),
    ],
    ids=["one line", "two lines", "padded", "longer than 200", "longer than 2000"],
)
def test_the_title_is_the_first_line_cut_at_200_and_a_longer_message_is_kept_in_the_description(
    message: str, title: str, description: str | None
) -> None:
    strategy = ToolStrategy(Result)
    b = Built(lambda m: said(strategy, "input_required", message), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None and asked.title == title and asked.description == description
        await live.cancel()

    run(go())


# --- 2. the answer is a new message ---------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES, ids=IDS)
def test_the_answer_is_the_next_human_message_of_the_same_thread_and_not_a_resume(strategy: Any) -> None:
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None
        await live.deliver(_answer(asked, {"answer": "north"}))
        tail = await rest(live)
        assert isinstance(tail[0], AnswerEvent) and isinstance(tail[-1], Done)
        assert b.calls.n == 2, "one model call for each turn"

        messages = await b.messages()
        humans_ = [m.text for m in messages if isinstance(m, HumanMessage)]
        assert humans_ == ["go", "north"], "the answer's text, as a message of the same thread"
        assert not (await b.graph.aget_state(CONFIG)).interrupts, "no interrupt was ever pending"
        done = (await b.graph.aget_state(CONFIG)).values["structured_response"]
        assert "Rolled out to north" in str(done)

        if isinstance(strategy, ProviderStrategy):
            assert json.loads(reply_text(tail)) == {"status": "completed", "message": "Rolled out to north"}, (
                "only an input_required reply is held back: a completed one is the reply (plan, point 1)"
            )
        else:
            assert reply_text(tail) == "", "a ToolStrategy reply has no text (plan, point 1)"

    run(go())


def test_the_answers_turn_counts_its_own_usage() -> None:
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        assert live.pending is not None
        await live.deliver(_answer(live.pending, {"answer": "north"}))
        tail = await rest(live)
        usages = [e for e in tail if isinstance(e, UsageEvent)]
        assert len(usages) == 1 and usages[0].usage.input_tokens == 6, "this turn's tokens, not the first turn's too"

    run(go())


def test_a_declined_question_ends_the_run_done_and_the_graph_is_not_called() -> None:
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None
        before = await b.graph.aget_state(CONFIG)
        await live.deliver(declined(asked, "not now"))
        tail = await rest(live)
        assert [type(e) for e in tail] == [AnswerEvent, Done], tail
        assert b.calls.n == 1, "the model was not called again"
        assert (await b.graph.aget_state(CONFIG)).config == before.config, "nothing was written"

    run(go())


# --- 3. what is not asked -------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES, ids=IDS)
@pytest.mark.parametrize(
    ("status", "message"),
    [("completed", "all set"), ("error", "it broke"), ("input_required", ""), ("input_required", "  \n ")],
    ids=["completed", "error", "input_required with no message", "input_required with a blank message"],
)
def test_only_input_required_with_a_message_is_asked(strategy: Any, status: str, message: str) -> None:
    b = Built(lambda m: said(strategy, status, message), strategy)

    async def go() -> None:
        events = [e async for e in Driver(b.source).start(THREAD, RunInput("go"))]
        assert not [e for e in events if isinstance(e, Ask)] and isinstance(events[-1], Done)
        if isinstance(strategy, ProviderStrategy):
            assert json.loads(reply_text(events)) == {"status": status, "message": message}, "so its JSON is the reply"

    run(go())


def test_a_json_reply_is_only_held_when_the_graph_has_a_structured_response() -> None:
    """A graph with no `structured_response` that says JSON in its text is not asked, and the text streams
    as it comes: the first piece is read while the model still waits (research R12)."""
    text = json.dumps({"status": "input_required", "message": QUESTION})
    gate = Gate(after=3)
    model = Scripted(script=lambda m: Say(text), gate=gate)

    async def talk(state: MessagesState, config: RunnableConfig) -> dict[str, Any]:
        return {"messages": [await model.ainvoke(state["messages"], config)]}

    builder = StateGraph(MessagesState)
    builder.add_node("talk", talk)
    builder.add_edge(START, "talk")
    builder.add_edge("talk", END)
    graph = builder.compile(checkpointer=memory_saver())
    assert "structured_response" not in graph.channels

    async def go() -> None:
        live = Driver(wrap(graph)).start(THREAD, RunInput("go"))
        first = await asyncio.wait_for(live.__anext__(), 5)
        assert isinstance(first, ReplyChunk) and first.text, "a piece of the JSON, read while the model waits"
        assert not gate.event.is_set()
        await asyncio.wait_for(gate.reached.wait(), 5)
        gate.event.set()
        events = [first] + [e async for e in live]
        assert not [e for e in events if isinstance(e, Ask)] and isinstance(events[-1], Done)
        assert reply_text(events) == text

    run(go())


def test_prose_streams_at_once_and_only_the_json_is_held() -> None:
    """A model that says something while it calls a tool, then ends with the JSON: the prose is the
    reply, the JSON is the question, and the reply is closed as one that had text."""
    strategy = ProviderStrategy(Result)
    runs: Counter[str] = Counter()

    def script(messages: list[BaseMessage]) -> Turn:
        if not tool_results(messages):
            return Call((NOTICE, {"text": "hi"}), text="Checking the regions. ")
        return said(strategy, "input_required", QUESTION)

    graph = agent(Scripted(script=script), [counted_tools(runs)[NOTICE]], memory_saver(), response_format=strategy)

    async def go() -> None:
        live, events = await ask(wrap(graph))
        chunks = [e for e in events if isinstance(e, ReplyChunk)]
        assert reply_text(events).strip() == "Checking the regions."
        assert chunks[-1].last and not any(c.last for c in chunks[:-1]), "closed once, as a reply that had text"
        assert isinstance(live.pending, Question) and live.pending.title == QUESTION
        await live.cancel()

    run(go())


def test_the_json_is_held_back_after_a_pause_too() -> None:
    """The turn pauses at a tool's interrupt, is answered, and only then ends `input_required`: the leg that
    goes on after the pause holds the JSON back as the first leg does."""
    strategy = ProviderStrategy(Result)

    def script(messages: list[BaseMessage]) -> Turn:
        return said(strategy, "input_required", QUESTION) if tool_results(messages) else Call(("ask_it", {}))

    source = wrap(asking_graph(strategy, script, Calls()))

    async def go() -> None:
        live, _ = await ask(source)
        first = live.pending
        assert isinstance(first, Question) and first.title == "Which one?" and first.answer_by.role == "person"
        await live.deliver(_answer(first, {"answer": "north"}))
        events = await until_pause(live)
        assert not [e for e in events if isinstance(e, ReplyChunk) and "{" in e.text], "the JSON was not the reply"
        asked = live.pending
        assert isinstance(asked, Question) and asked.id.startswith("lg-ir-") and asked.title == QUESTION
        assert asked.answer_by.role == "caller"
        await live.cancel()

    run(go())


def test_text_that_starts_with_a_brace_and_no_node_update_carried_is_the_reply_when_the_turn_ends() -> None:
    """What is kept apart waits for its node update. A node that says it but returns no message never gives
    one: the text is reply text after all, and is closed as the reply's last piece."""
    text = '{"note": "this is not a structured reply"}'
    model = Scripted(script=lambda m: Say(text))

    class Stated(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        structured_response: Any

    async def talk(state: Stated, config: RunnableConfig) -> dict[str, Any]:
        await model.ainvoke(state["messages"], config)  # it streams, and the node returns none of it
        return {"structured_response": None}

    builder = StateGraph(Stated)
    builder.add_node("talk", talk)
    builder.add_edge(START, "talk")
    builder.add_edge("talk", END)
    graph = builder.compile(checkpointer=memory_saver())

    async def go() -> None:
        events = [e async for e in Driver(wrap(graph)).start(THREAD, RunInput("go"))]
        assert isinstance(events[-1], Done) and not [e for e in events if isinstance(e, Ask)]
        chunks = [e for e in events if isinstance(e, ReplyChunk)]
        assert reply_text(events) == text and chunks[-1].last, events

    run(go())


# The reply's own rules, on their own: what is kept apart, and when it leaves (`Reply` is pure).


def test_a_message_that_starts_with_a_brace_is_kept_apart_and_dropped_when_it_asks() -> None:
    reply = Reply(structured=True)
    assert reply.feed('{"status": ', "m1") == [] and reply.feed('"input_required"}', "m1") == []
    assert reply.resolve("m1", True) == []
    assert reply.end_turn(False) == [] and not reply.spoke(AIMessage(content='{"status": "input_required"}', id="m1"))


def test_a_message_kept_apart_that_does_not_ask_is_reply_text() -> None:
    reply = Reply(structured=True)
    assert reply.feed('{"a": 1}', "m1") == []
    assert reply.resolve("m1", False) == []  # it is now the newest piece, held for the last-chunk mark
    assert reply.end_turn(True) == [ReplyChunk('{"a": 1}', last=True)]


def test_blanks_do_not_decide_what_a_message_is_until_its_first_word() -> None:
    held = Reply(structured=True)
    assert held.feed("\n", "m1") == [] and held.feed('{"a": 1}', "m1") == [], "blanks, then a brace: kept apart"
    assert held.resolve("m1", True) == [] and held.end_turn(False) == []

    prose = Reply(structured=True)
    assert prose.feed(" ", "m1") == [] and prose.feed("Hello", "m1") == [], "blanks, then a word: prose, all of it"
    assert prose.end_turn(True) == [ReplyChunk(" Hello", last=True)]


def test_what_is_kept_apart_when_the_leg_ends_is_released_as_reply_text() -> None:
    reply = Reply(structured=True)
    assert reply.feed('{"a": 1}', "m1") == []
    assert reply.release_all() == []
    assert reply.end_turn(False) == [ReplyChunk('{"a": 1}', last=True)]


def test_a_structured_reply_left_from_an_earlier_turn_is_not_asked_again() -> None:
    """The state still holds `input_required` after a turn whose own update did not set a structured
    reply: only what this leg's updates carried is read (R12)."""

    class Held(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        structured_response: Any

    def node(state: Held) -> dict[str, Any]:
        if humans(state["messages"]) == 1:
            return {
                "messages": [AIMessage(content=QUESTION)],
                "structured_response": {"status": "input_required", "message": QUESTION},
            }
        return {"messages": [AIMessage(content="Thanks, rolling out.")]}  # does not touch the structured reply

    builder = StateGraph(Held)
    builder.add_node("answer", node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    graph = builder.compile(checkpointer=memory_saver())

    async def go() -> None:
        live, _ = await ask(wrap(graph))
        assert live.pending is not None
        await live.deliver(_answer(live.pending, {"answer": "north"}))
        tail = await rest(live)
        assert not [e for e in tail if isinstance(e, Ask)] and isinstance(tail[-1], Done)
        assert (await graph.aget_state(CONFIG)).values["structured_response"]["status"] == "input_required", "still left"
        assert "Thanks, rolling out." in reply_text(tail)

    run(go())


# --- 4. an answer that is no longer for a pending question -----------------------------------------


async def lost(source: Any, asked: Any, text: str = "north") -> Error:
    events = [e async for e in Driver(source).resume(THREAD, asked, _answer(asked, {"answer": text}))]
    assert [type(e) for e in events] == [AnswerEvent, Error], events
    assert isinstance(events[-1], Error)
    return events[-1]


def test_an_answer_after_the_conversation_moved_on_ends_lost_and_does_not_call_the_graph() -> None:
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None
        await live.cancel()

        # The caller sends a message of its own instead of answering: a human message now follows.
        moved = Driver(b.source).start(THREAD, RunInput("never mind, use south"))
        await rest(moved)
        calls = b.calls.n
        error = await lost(b.source, asked)
        assert error.code == "lost" and b.calls.n == calls, "the graph was not called"
        assert [m.text for m in await b.messages() if isinstance(m, HumanMessage)] == ["go", "never mind, use south"]

    run(go())


def test_an_answer_when_a_human_message_no_turn_has_answered_yet_follows_ends_lost() -> None:
    """The saved reply still asks, but the last word in the thread is a person's: the question was passed by."""
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None
        await live.cancel()
        await b.graph.aupdate_state(CONFIG, {"messages": [HumanMessage("a message that came another way")]})
        assert (await b.graph.aget_state(CONFIG)).values["structured_response"].status == "input_required"
        error = await lost(b.source, asked)
        assert error.code == "lost" and b.calls.n == 1

    run(go())


def test_no_question_waits_on_a_saved_reply_while_a_later_turn_is_stopped_at_an_interrupt() -> None:
    """The reply the state holds is the one of an earlier turn (a graph that keeps its `structured_response` from
    turn to turn), and the thread is now in the middle of another, stopped at an interrupt: a question named after
    the new last message is not one the thread asked."""

    class Kept(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        structured_response: Any

    def speak(state: Kept) -> dict[str, Any]:
        if humans(state["messages"]) == 1:
            return {
                "messages": [AIMessage(content=QUESTION)],
                "structured_response": {"status": "input_required", "message": QUESTION},
            }
        return {"messages": [AIMessage(content="Let me check one thing.")]}  # the saved reply is left as it was

    def gate(state: Kept) -> dict[str, Any]:
        if humans(state["messages"]) > 1:
            interrupt("Which one?")
        return {}

    builder = StateGraph(Kept)
    builder.add_node("speak", speak)
    builder.add_node("gate", gate)
    builder.add_edge(START, "speak")
    builder.add_edge("speak", "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=memory_saver())
    source = wrap(graph)

    async def go() -> None:
        live, _ = await ask(source)
        asked = live.pending
        assert asked is not None and asked.title == QUESTION
        await live.deliver(_answer(asked, {"answer": "north"}))
        await until_pause(live)
        stopped = live.pending
        assert stopped is not None and stopped.id != asked.id and stopped.title == "Which one?"
        await live.cancel()

        state = await graph.aget_state(CONFIG)
        assert state.interrupts and state.values["structured_response"]["status"] == "input_required", "stale"
        (last_ai, *_) = [m for m in reversed(state.values["messages"]) if isinstance(m, AIMessage)]
        phantom = asked.model_copy(update={"id": f"lg-ir-{last_ai.id}"})
        before = len(state.values["messages"])
        error = await lost(source, phantom)
        assert error.code == "lost"
        assert len((await graph.aget_state(CONFIG)).values["messages"]) == before, "the graph was not called"

    run(go())


def test_an_answer_to_a_question_the_graph_never_asked_ends_lost() -> None:
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert isinstance(asked, Question)
        await live.cancel()
        other = asked.model_copy(update={"id": "lg-ir-some-other-message"})
        error = await lost(b.source, other)
        assert error.code == "lost" and b.calls.n == 1

    run(go())


def test_an_answer_to_a_reply_that_no_longer_asks_ends_lost() -> None:
    """The graph's state holds a structured reply that is no longer `input_required`: nothing is pending."""
    strategy = ToolStrategy(Result)
    b = Built(regions(strategy), strategy)

    async def go() -> None:
        live, _ = await ask(b.source)
        asked = live.pending
        assert asked is not None
        await live.cancel()
        await b.graph.aupdate_state(CONFIG, {"structured_response": Result(status="completed", message="done")})
        error = await lost(b.source, asked)
        assert error.code == "lost" and b.calls.n == 1

    run(go())


# --- 5. across a restart ----------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning")
@pytest.mark.parametrize("strategy", STRATEGIES, ids=IDS)
def test_the_question_survives_a_restart_with_the_same_id(strategy: Any, tmp_path: Path) -> None:
    path = tmp_path / "ir.db"
    calls = Calls()

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = Built(regions(strategy), strategy, saver_a, calls)
            live, _ = await ask(a.source)
            first = live.pending
            assert isinstance(first, Question)
            await live.cancel()

        async with restart(path) as saver_b:
            b = Built(regions(strategy), strategy, saver_b, calls)
            resumed = Driver(b.source).resume(THREAD, first, _answer(first, {"answer": "south"}))
            tail = await rest(resumed)
            assert isinstance(tail[-1], Done), tail
            assert [m.text for m in await b.messages() if isinstance(m, HumanMessage)] == ["go", "south"]
            assert "Rolled out to south" in str((await b.graph.aget_state(CONFIG)).values["structured_response"])

    run(go())
