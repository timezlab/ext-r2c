"""Wrapping a graph: the three checks, the card, the options, the in-memory warning
(spec 006, research R2; FR-001 to FR-004, FR-026, D11).

Real graphs and real checkpointers; the model is scripted and says one word. Nothing here runs the
graph except the FR-001 test, which compares the graph before and after a run.
"""

from __future__ import annotations

import typing
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import pytest
from langchain_core.messages import AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, PydanticUserError
from typing_extensions import TypedDict  # pydantic refuses `typing.TypedDict` before Python 3.12

from ext_r2c.bridges.langgraph import LangGraphAgent
from ext_r2c.core import CardInfo, Driver, Done, RunInput, thread_id

from langgraph_graphs import agent, memory_saver, run, sqlite_saver, wrap
from langgraph_models import Calls, Say, Scripted

THREAD = thread_id("a2a", "owner-1", "ctx-1")


def _model() -> Scripted:
    return Scripted(script=lambda messages: Say("hello there"))


def _graph(saver: Any = None, *, name: str = "agent") -> Any:
    return agent(_model(), [], memory_saver() if saver is None else saver, name=name)


class _Plain(TypedDict):
    x: int


def _plain_graph(saver: Any) -> Any:
    builder = StateGraph(_Plain)
    builder.add_node("step", lambda state: {"x": 1})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


def _messages_graph(saver: Any) -> Any:
    builder = StateGraph(MessagesState)
    builder.add_node("step", lambda state: {"messages": []})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


# --- 1. not a compiled graph -------------------------------------------------------------------


def test_an_object_that_is_not_a_graph_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="compiled"):
        LangGraphAgent(object())  # type: ignore[arg-type]


def test_an_uncompiled_state_graph_is_a_type_error_that_says_how_to_compile() -> None:
    builder = StateGraph(MessagesState)
    builder.add_node("step", lambda state: {"messages": []})
    with pytest.raises(TypeError, match=r"\.compile\(checkpointer="):
        LangGraphAgent(builder)  # type: ignore[arg-type]


# --- 2. no checkpointer ------------------------------------------------------------------------


@pytest.mark.parametrize("saver", [None, True, False])
def test_a_graph_without_a_checkpointer_is_a_value_error(saver: Any) -> None:
    with pytest.raises(ValueError, match="checkpointer"):
        LangGraphAgent(_messages_graph(saver))


def test_a_checkpointer_that_is_not_a_saver_is_a_value_error() -> None:
    graph = _messages_graph(memory_saver())
    graph.checkpointer = object()  # only a hand-edited graph can hold one
    with pytest.raises(ValueError, match="checkpointer"):
        LangGraphAgent(graph)


# --- 3. no `messages` in the input (D1) --------------------------------------------------------


def test_a_state_with_no_messages_is_a_value_error_that_names_the_input() -> None:
    with pytest.raises(ValueError, match="messages"):
        LangGraphAgent(_plain_graph(memory_saver()))


def test_the_checks_run_in_order() -> None:
    # No checkpointer *and* no messages: the checkpointer is named first.
    with pytest.raises(ValueError, match="checkpointer"):
        LangGraphAgent(_plain_graph(None))


# A state can hold a field pydantic cannot describe (a client, a connection: LangGraph never asks it to),
# and before Python 3.12 pydantic refuses `typing.TypedDict`, which LangGraph's own documents use. The
# graph runs all the same, so wrapping it must not depend on a schema pydantic builds (principle III).


class _Handle:
    """A thing a node keeps in the state that no JSON schema can describe."""


Messages = Annotated[list[AnyMessage], add_messages]


class _TypedWithHandle(TypedDict):
    messages: Messages
    handle: _Handle


class _TypedWithHandleNoMessages(TypedDict):
    note: str
    handle: _Handle


class _TypedBase(TypedDict):
    messages: Messages


class _TypedInherits(_TypedBase):
    handle: _Handle


class _FromTyping(typing.TypedDict):
    messages: Messages


@dataclass
class _DataBase:
    messages: Messages


@dataclass
class _DataInherits(_DataBase):
    handle: _Handle | None = None


class _ModelWithHandle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    messages: Messages
    handle: _Handle | None = None


class _ModelWithHandleNoMessages(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    note: str = ""
    handle: _Handle | None = None


def _graph_with_state(state: Any, saver: Any) -> Any:
    builder = StateGraph(state)
    builder.add_node("step", lambda s: {})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


@pytest.mark.parametrize(
    "state",
    [_TypedWithHandle, _TypedInherits, _FromTyping, _ModelWithHandle, _DataInherits],
    ids=[
        "typed dict with a handle",
        "typed dict that inherits messages",
        "typing.TypedDict",
        "model with a handle",
        "dataclass that inherits messages",
    ],
)
def test_a_state_pydantic_cannot_describe_is_still_wrapped(state: Any) -> None:
    assert wrap(_graph_with_state(state, memory_saver())).pause == "checkpoint"


@pytest.mark.parametrize(
    "state",
    [_TypedWithHandleNoMessages, _ModelWithHandleNoMessages],
    ids=["typed dict with a handle", "model with a handle"],
)
def test_such_a_state_with_no_messages_is_still_refused_for_that_reason(state: Any) -> None:
    with pytest.raises(ValueError, match="messages"):
        LangGraphAgent(_graph_with_state(state, memory_saver()))


def test_a_graph_with_no_state_class_to_read_keeps_the_error_pydantic_raised() -> None:
    """The keys are read only where a state class exists; for anything else the error is not hidden."""
    from types import SimpleNamespace

    from ext_r2c.bridges.langgraph.agent import _accepts_messages

    def refuse() -> Any:
        raise PydanticUserError("no schema", code=None)

    with pytest.raises(PydanticUserError, match="no schema"):
        _accepts_messages(SimpleNamespace(get_input_jsonschema=refuse))  # type: ignore[arg-type]


# --- 4. the options ----------------------------------------------------------------------------


def test_expose_tools_holding_a_non_string_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="expose_tools"):
        wrap(_graph(), expose_tools=["search", 7])


def test_the_options_are_keyword_only() -> None:
    card = CardInfo("Writer", "Writes.", "1.0.0")
    with pytest.raises(TypeError):
        LangGraphAgent(_graph(), card)  # type: ignore[misc]


# --- 5. the card -------------------------------------------------------------------------------


def test_the_card_is_the_argument_as_given() -> None:
    card = CardInfo("Writer", "Writes the report.", "1.2.3")
    assert wrap(_graph(), card=card).card is card


def test_the_default_card_names_the_graph() -> None:
    card = wrap(_graph(name="stock_writer")).card
    assert card == CardInfo("stock_writer", "A LangGraph agent served through R2C.", "0.0.0")


def test_the_agent_is_a_checkpoint_source_a_driver_accepts() -> None:
    source = wrap(_graph())
    assert source.pause == "checkpoint"
    Driver(source)  # the driver refuses a source with no style, or no run or resume


# --- 6. the in-memory warning (D11) ------------------------------------------------------------


def test_an_in_memory_saver_warns_once_per_construction() -> None:
    graph = _graph(InMemorySaver())
    for n in (1, 2):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            LangGraphAgent(graph)
        users = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(users) == 1, f"construction {n}: {[str(w.message) for w in caught]}"
        text = str(users[0].message)
        assert "not survive a restart" in text and "checkpointer" in text
        assert users[0].filename == __file__, "the warning points at the line that wrapped the graph"


def test_a_durable_saver_gives_no_warning(tmp_path: Path) -> None:
    async def go() -> None:
        async with sqlite_saver(tmp_path / "wrap.db") as saver:
            graph = _graph(saver)
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                LangGraphAgent(graph)

    run(go())


# --- 7. FR-001: the graph is not touched -------------------------------------------------------


def test_the_graph_is_the_same_object_after_a_run() -> None:
    graph = _graph()
    before = (graph.name, graph.checkpointer, dict(graph.nodes), graph.config, type(graph))
    source = wrap(graph)

    async def go() -> list[Any]:
        return [event async for event in Driver(source).start(THREAD, RunInput("Write the report"))]

    events = run(go())
    assert isinstance(events[-1], Done)
    after = (graph.name, graph.checkpointer, dict(graph.nodes), graph.config, type(graph))
    assert after[0] == before[0] and after[2:] == before[2:]
    assert after[1] is before[1], "the same checkpointer object"
    assert all(after[2][k] is before[2][k] for k in before[2]), "the same node objects"
    assert after[3] == before[3] and "callbacks" not in after[3], "no callback was left on the graph's own config"


def test_a_graph_wrapped_twice_serves_both_agents() -> None:
    graph = _graph()

    async def reply(source: Any, thread: str) -> str:
        events = [event async for event in Driver(source).start(thread, RunInput("hi"))]
        return "".join(e.text for e in events if hasattr(e, "text"))

    async def go() -> list[str]:
        return [await reply(wrap(graph), THREAD), await reply(wrap(graph), thread_id("a2a", "owner-1", "ctx-2"))]

    assert run(go()) == ["hello there", "hello there"]


def test_wrapping_calls_no_model_and_writes_no_state() -> None:
    # Wrapping reads the graph's schema and checkpointer only.
    calls = Calls()
    graph = agent(Scripted(script=lambda messages: Say("never"), calls=calls), [], memory_saver())
    wrap(graph)
    assert calls.n == 0
    assert not graph.get_state({"configurable": {"thread_id": "x"}}).values
