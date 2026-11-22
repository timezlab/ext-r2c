"""LangChain tools as `ToolSpec`s (spec 006, story 6; FR-024, FR-025; research R16; SC-011).

Real LangChain tools of the five kinds (`@tool`, a pydantic `args_schema`, a plain JSON Schema
`args_schema`, an async-only `StructuredTool`, a `BaseTool` subclass), real `ToolSpec`s of the core.
The body of each tool counts its runs, so "the tool did not run" is something a test can see.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections import Counter
from typing import Annotated, Any

import pytest
from langchain.tools import InjectedState, InjectedStore, ToolRuntime
from langchain_core.tools import (
    BaseTool,
    InjectedToolArg,
    InjectedToolCallId,
    StructuredTool,
    Tool,
    ToolException,
    tool,
)
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

import ext_r2c.bridges.langgraph as bridge
from ext_r2c.bridges.langgraph import tool_from_langchain, tools_from_langchain
from ext_r2c.core import InvalidArguments, ToolSpec, tool_from_function

from langgraph_graphs import run

PLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"item": {"type": "string"}, "quantity": {"type": "integer"}},
    "required": ["item"],
}


class Entry(BaseModel):
    item: str
    quantity: int = 1


class Strict(BaseModel):
    """Arguments the model-visible schema cannot fully say: no other key, and a quantity of one or more."""

    model_config = ConfigDict(extra="forbid")

    item: str
    quantity: int = 1

    @field_validator("quantity")
    @classmethod
    def at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least one")
        return value


class Subclassed(BaseTool):
    name: str = "subclassed"
    description: str = "Look an entry up (subclassed)."
    args_schema: type[BaseModel] | None = Entry
    runs: Any = None

    def _run(self, item: str, quantity: int = 1) -> str:
        self.runs[self.name] += 1
        return f"{item} x{quantity}"


def make_tools(runs: Counter[str]) -> dict[str, BaseTool]:
    """One tool of each kind. All take `item` and an optional `quantity` and answer `"<item> x<quantity>"`."""

    @tool("decorated")
    def decorated(item: str, quantity: int = 1) -> str:
        """Look an entry up (decorated)."""
        runs["decorated"] += 1
        return f"{item} x{quantity}"

    def pydantic_body(item: str, quantity: int = 1) -> str:
        runs["pydantic"] += 1
        return f"{item} x{quantity}"

    def plain_body(**kwargs: Any) -> str:
        runs["plain"] += 1
        return f"{kwargs['item']} x{kwargs.get('quantity', 1)}"

    async def async_body(item: str, quantity: int = 1) -> str:
        runs["async_only"] += 1
        return f"{item} x{quantity}"

    return {
        "decorated": decorated,
        "pydantic": StructuredTool.from_function(
            pydantic_body, name="pydantic", description="Look an entry up (pydantic).", args_schema=Entry
        ),
        "plain": StructuredTool.from_function(
            plain_body, name="plain", description="Look an entry up (plain).", args_schema=dict(PLAIN_SCHEMA)
        ),
        "async_only": StructuredTool.from_function(
            coroutine=async_body, name="async_only", description="Look an entry up (async).", args_schema=Entry
        ),
        "subclassed": Subclassed(runs=runs),
    }


KINDS = ["decorated", "pydantic", "plain", "async_only", "subclassed"]


def call(spec: ToolSpec, args: dict[str, Any]) -> Any:
    return run(spec.call(args))


def refused(spec: ToolSpec, args: dict[str, Any]) -> InvalidArguments:
    with pytest.raises(InvalidArguments) as caught:
        call(spec, args)
    return caught.value


# --- 1. the ToolSpec: name, description, model-visible schema --------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_tool_becomes_a_toolspec_with_its_name_description_and_schema(kind: str) -> None:
    tools = make_tools(Counter())
    tool_ = tools[kind]
    spec = tool_from_langchain(tool_)

    assert isinstance(spec, ToolSpec)
    assert (spec.name, spec.description) == (tool_.name, tool_.description)
    schema = spec.input_schema
    assert schema["type"] == "object" and schema["required"] == ["item"]
    assert list(schema["properties"]) == ["item", "quantity"]
    assert schema["properties"]["item"]["type"] == "string"
    assert schema["properties"]["quantity"]["type"] == "integer"
    assert "title" not in schema, "the name is the ToolSpec's, as with tool_from_function"
    assert "description" not in schema, "a plain JSON Schema comes back from LangChain with the description added"


def test_a_plain_json_schema_comes_through_as_it_was_given() -> None:
    spec = tool_from_langchain(make_tools(Counter())["plain"])
    assert spec.input_schema == PLAIN_SCHEMA


@pytest.mark.parametrize("kind", ["pydantic", "plain"])
def test_the_schema_is_a_copy_that_changing_does_not_reach_the_tool(kind: str) -> None:
    tool_ = make_tools(Counter())[kind]
    first = tool_from_langchain(tool_)
    first.input_schema["properties"]["item"]["type"] = "integer"
    first.input_schema["required"].append("quantity")

    again = tool_from_langchain(tool_)
    assert again.input_schema["properties"]["item"]["type"] == "string"
    assert again.input_schema["required"] == ["item"]
    seen = tool_.tool_call_schema
    shape = seen.model_json_schema() if hasattr(seen, "model_json_schema") else seen
    assert shape["properties"]["item"]["type"] == "string", "the tool's own schema is not touched"
    if isinstance(tool_.args_schema, dict):
        assert tool_.args_schema == PLAIN_SCHEMA, "nor is the dict the tool was given"


def test_the_spec_has_the_same_fields_as_one_made_from_a_function() -> None:
    def reorder(item: str, quantity: int = 1) -> str:
        """Reorder an item."""
        return f"{item} x{quantity}"

    ours = tool_from_langchain(tool(reorder))
    theirs = tool_from_function(reorder)
    assert [f.name for f in dataclasses.fields(ours)] == [f.name for f in dataclasses.fields(theirs)]
    assert (ours.name, ours.description) == (theirs.name, theirs.description)

    def shape(spec: ToolSpec) -> Any:
        props = spec.input_schema["properties"]
        return spec.input_schema["required"], {k: (v["type"], v.get("default")) for k, v in props.items()}

    assert shape(ours) == shape(theirs)


def test_a_value_that_is_not_a_tool_is_refused() -> None:
    with pytest.raises(TypeError, match="function"):
        tool_from_langchain(lambda item: item)  # type: ignore[arg-type]


# --- 2. a valid call runs the tool ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_valid_call_runs_the_tool_and_returns_its_result(kind: str) -> None:
    runs: Counter[str] = Counter()
    spec = tool_from_langchain(make_tools(runs)[kind])

    assert call(spec, {"item": "A-113", "quantity": 3}) == "A-113 x3"
    assert runs[kind] == 1
    assert call(spec, {"item": "B-7"}) == "B-7 x1", "a key left out takes the tool's own default"
    assert runs[kind] == 2


@pytest.mark.parametrize("kind", ["decorated", "plain"])
def test_a_sync_tool_does_not_block_the_event_loop(kind: str) -> None:
    def slow(**kwargs: Any) -> str:
        time.sleep(0.3)
        return "slept"

    tools: dict[str, BaseTool] = {
        "decorated": StructuredTool.from_function(slow, name="slow_one", description="Sleeps.", args_schema=Entry),
        "plain": StructuredTool.from_function(slow, name="slow_two", description="Sleeps.", args_schema=PLAIN_SCHEMA),
    }
    spec = tool_from_langchain(tools[kind])

    async def go() -> None:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            assert await spec.call({"item": "a"}) == "slept"
        finally:
            task.cancel()
        assert ticks >= 5, f"the loop ticked {ticks} times while the tool ran: it was blocked"

    run(go())


def test_what_the_tool_raises_is_not_turned_into_a_problem_with_the_arguments() -> None:
    """The arguments were fine; the tool failed. That is the tool's own error, whichever it is."""

    class Broken(Exception):
        pass

    @tool("fails")
    def fails(item: str) -> str:
        """Always fails."""
        raise ToolException("the shelf is empty")

    @tool("parses")
    def parses(item: str) -> str:
        """Parses something of its own, badly."""
        Entry.model_validate({"quantity": "x"})
        return item

    @tool("explodes")
    def explodes(item: str) -> str:
        """Fails in a way nobody planned."""
        raise Broken(item)

    with pytest.raises(ToolException, match="the shelf is empty"):
        call(tool_from_langchain(fails), {"item": "a"})
    with pytest.raises(ValidationError):
        call(tool_from_langchain(parses), {"item": "a"})
    with pytest.raises(Broken):
        call(tool_from_langchain(explodes), {"item": "a"})


# --- 3. arguments that break the schema never run the tool ----------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_arguments_that_break_the_schema_do_not_run_the_tool(kind: str) -> None:
    runs: Counter[str] = Counter()
    spec = tool_from_langchain(make_tools(runs)[kind])

    caught = refused(spec, {"quantity": "three"})  # `item` is missing, `quantity` is the wrong type
    assert [p.key for p in caught.problems] == ["item", "quantity"], "one problem per key, in the schema's order"
    assert {p.code for p in caught.problems} == {"invalid_args"}
    assert all(isinstance(p.message, str) and p.message for p in caught.problems)
    assert runs[kind] == 0, "the tool did not run"

    caught = refused(spec, {"item": 7})
    assert [p.key for p in caught.problems] == ["item"]
    assert runs[kind] == 0


@pytest.mark.parametrize("kind", KINDS)
def test_an_empty_call_names_what_is_missing(kind: str) -> None:
    runs: Counter[str] = Counter()
    caught = refused(tool_from_langchain(make_tools(runs)[kind]), {})
    assert [(p.code, p.key) for p in caught.problems] == [("invalid_args", "item")]
    assert not runs


def test_a_plain_json_schema_tool_is_checked_though_langchain_does_not_check_it() -> None:
    """LangChain passes the arguments of a tool with a dict `args_schema` straight to the function."""
    runs: Counter[str] = Counter()
    spec = tool_from_langchain(make_tools(runs)["plain"])
    refused(spec, {"item": "a", "quantity": "many"})
    refused(spec, {"quantity": 2})
    assert not runs


def test_one_problem_per_key_even_when_a_key_breaks_two_rules() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 3, "pattern": "^a"},
            "size": {"type": "integer", "minimum": 1},
        },
        "required": ["name"],
    }
    tool_ = StructuredTool.from_function(lambda **kw: "ok", name="shaped", description="d", args_schema=schema)
    caught = refused(tool_from_langchain(tool_), {"size": 0, "name": "b"})
    assert [p.key for p in caught.problems] == ["name", "size"], "in the schema's order, `name` once"


def test_a_key_the_schema_forbids_is_a_problem_with_no_key_and_comes_first() -> None:
    schema = {
        "type": "object",
        "properties": {"item": {"type": "string"}},
        "required": ["item"],
        "additionalProperties": False,
    }
    runs: Counter[str] = Counter()

    def body(**kw: Any) -> str:
        runs["body"] += 1
        return "ok"

    spec = tool_from_langchain(StructuredTool.from_function(body, name="closed", description="d", args_schema=schema))
    caught = refused(spec, {"item": 1, "colour": "red"})
    assert [p.key for p in caught.problems] == [None, "item"]
    assert not runs


@pytest.mark.parametrize("args, keys", [({"item": "a", "colour": "red"}, ["colour"]), ({"item": "a", "quantity": 0}, ["quantity"])])
def test_what_the_pydantic_schema_cannot_say_is_still_refused_before_the_tool_runs(
    args: dict[str, Any], keys: list[str]
) -> None:
    """`tool_call_schema` leaves out `extra="forbid"` and the model's validators. LangChain would refuse
    the call with a raw pydantic error, so it is turned into the same `InvalidArguments` (as the core does)."""
    runs: Counter[str] = Counter()

    def body(item: str, quantity: int = 1) -> str:
        runs["body"] += 1
        return "ok"

    strict = StructuredTool.from_function(body, name="strict", description="d", args_schema=Strict)
    spec = tool_from_langchain(strict)
    assert "additionalProperties" not in spec.input_schema, "the schema shown does not say it: that is the case"

    caught = refused(spec, args)
    assert [p.key for p in caught.problems] == keys and {p.code for p in caught.problems} == {"invalid_args"}
    assert not runs
    assert call(spec, {"item": "a", "quantity": 2}) == "ok" and runs["body"] == 1


def test_the_same_bad_arguments_give_the_same_problems_as_a_function_tool() -> None:
    def reorder(item: str, quantity: int = 1) -> str:
        """Reorder an item."""
        return item

    ours, theirs = tool_from_langchain(tool(reorder)), tool_from_function(reorder)
    for args in ({}, {"quantity": "three"}, {"item": 1, "quantity": 2.5}):
        a, b = refused(ours, args), refused(theirs, args)
        assert [(p.code, p.key) for p in a.problems] == [(p.code, p.key) for p in b.problems], args


# --- 4. an injected argument is refused at conversion ---------------------------------------------------


def injected(arg: str) -> BaseTool:
    """A tool that needs `arg`, which only a running graph supplies."""
    if arg == "state":

        @tool("needs_state")
        def needs_state(item: str, state: Annotated[dict[str, Any], InjectedState]) -> str:
            """Needs the graph's state."""
            return item

        return needs_state
    if arg == "store":

        @tool("needs_store")
        def needs_store(item: str, store: Annotated[Any, InjectedStore()]) -> str:
            """Needs the graph's store."""
            return item

        return needs_store
    if arg == "runtime":

        @tool("needs_runtime")
        def needs_runtime(item: str, runtime: ToolRuntime) -> str:
            """Needs the runtime."""
            return item

        return needs_runtime
    if arg == "call_id":

        @tool("needs_call_id")
        def needs_call_id(item: str, call_id: Annotated[str, InjectedToolCallId]) -> str:
            """Needs the id of the call."""
            return item

        return needs_call_id

    @tool("needs_extra")
    def needs_extra(item: str, extra: Annotated[int, InjectedToolArg]) -> str:
        """Needs an argument the caller supplies."""
        return item

    return needs_extra


ARGUMENTS = ["state", "store", "runtime", "call_id", "extra"]


@pytest.mark.parametrize("arg", ARGUMENTS)
def test_an_injected_argument_is_refused_at_conversion_naming_tool_and_argument(arg: str) -> None:
    tool_ = injected(arg)
    with pytest.raises(TypeError) as caught:
        tool_from_langchain(tool_)
    assert tool_.name in str(caught.value) and arg in str(caught.value)


def test_every_injected_argument_of_a_tool_is_named() -> None:
    @tool("needs_both")
    def needs_both(
        item: str,
        state: Annotated[dict[str, Any], InjectedState],
        runtime: ToolRuntime,
    ) -> str:
        """Needs the state and the runtime."""
        return item

    with pytest.raises(TypeError) as caught:
        tool_from_langchain(needs_both)
    message = str(caught.value)
    assert "needs_both" in message and "state" in message and "runtime" in message


def test_a_subclass_that_leaves_its_schema_to_langchain_converts_and_runs() -> None:
    """No `args_schema`: LangChain reads the arguments from `_run`. They are the tool's, injected or not."""

    class Inferred(BaseTool):
        name: str = "inferred"
        description: str = "Look an entry up (inferred)."

        def _run(self, item: str, quantity: int = 1) -> str:
            return f"{item} x{quantity}"

    spec = tool_from_langchain(Inferred())
    assert list(spec.input_schema["properties"]) == ["item", "quantity"] and spec.input_schema["required"] == ["item"]
    assert call(spec, {"item": "a", "quantity": 2}) == "a x2"
    assert [p.key for p in refused(spec, {"quantity": 2}).problems] == ["item"]


def test_a_subclass_that_leaves_its_schema_to_langchain_is_refused_for_an_injected_argument() -> None:
    class NeedsRuntime(BaseTool):
        name: str = "needs_it"
        description: str = "Needs the runtime."

        def _run(self, item: str, runtime: ToolRuntime) -> str:
            return item

    with pytest.raises(TypeError) as caught:
        tool_from_langchain(NeedsRuntime())
    assert "needs_it" in str(caught.value) and "runtime" in str(caught.value)


def test_a_legacy_single_string_tool_is_refused_for_having_no_schema_to_describe_it() -> None:
    """`Tool` with no `args_schema` says its argument is `tool_input`, but its input model is made from
    `_run(*args, config, **kwargs)`: no schema of its own to pass on. Refused, not converted into nonsense."""
    legacy = Tool(name="echo", func=lambda text: f"echo:{text}", description="Echo a string.")
    with pytest.raises(TypeError) as caught:
        tool_from_langchain(legacy)
    message = str(caught.value)
    assert "echo" in message and "args_schema" in message
    assert "config" not in message and "kwargs" not in message, "no argument of its signature is named as injected"


def test_a_tool_with_no_arguments_converts_and_runs() -> None:
    @tool("ping")
    def ping() -> str:
        """Say pong."""
        return "pong"

    # LangChain's own `args` of a dict schema with no `properties` raises: the conversion must not ask it.
    bare = StructuredTool.from_function(
        lambda **kw: "pong", name="bare", description="Say pong.", args_schema={"type": "object"}
    )
    for tool_ in (ping, bare):
        spec = tool_from_langchain(tool_)
        assert spec.input_schema.get("properties", {}) == {}
        assert call(spec, {}) == "pong"


def test_a_tool_with_a_plain_json_schema_has_nothing_to_refuse() -> None:
    schema = {"type": "object", "properties": {"state": {"type": "string"}}, "required": ["state"]}
    tool_ = StructuredTool.from_function(lambda **kw: "ok", name="stateful", description="d", args_schema=schema)
    assert call(tool_from_langchain(tool_), {"state": "open"}) == "ok", "here `state` is an ordinary argument"


# --- 5. lists -------------------------------------------------------------------------------------------


def test_a_list_converts_in_order() -> None:
    tools = make_tools(Counter())
    order = ["subclassed", "plain", "decorated", "async_only", "pydantic"]
    specs = tools_from_langchain([tools[k] for k in order])
    assert isinstance(specs, list) and all(isinstance(s, ToolSpec) for s in specs)
    assert [s.name for s in specs] == order
    assert [s.name for s in tools_from_langchain(reversed([tools[k] for k in order]))] == order[::-1]


def test_one_refusal_refuses_the_whole_list() -> None:
    tools = make_tools(Counter())
    for position in range(3):
        tools_list: list[BaseTool] = [tools["decorated"], tools["pydantic"]]
        tools_list.insert(position, injected("state"))
        with pytest.raises(TypeError, match="needs_state"):
            tools_from_langchain(tools_list)


def test_an_empty_list_converts_to_an_empty_list() -> None:
    assert tools_from_langchain([]) == []
    assert tools_from_langchain(t for t in ()) == []


def test_any_iterable_of_tools_converts() -> None:
    tools = make_tools(Counter())
    assert [s.name for s in tools_from_langchain(t for t in (tools["decorated"], tools["plain"]))] == [
        "decorated",
        "plain",
    ]


# --- 6. where the names are ----------------------------------------------------------------------------


def test_both_names_are_public_in_the_bridge() -> None:
    assert {"tool_from_langchain", "tools_from_langchain", "LangGraphAgent"} <= set(bridge.__all__)
    from ext_r2c.bridges.langgraph import tools

    assert {"tool_from_langchain", "tools_from_langchain"} <= set(tools.__all__)
