"""LangChain tools (spec 006, research R16).

Public: `tool_from_langchain` and `tools_from_langchain` make `ToolSpec`s of the core out of LangChain
tools, with no second declaration. Private: the arguments schema of a tool (to offer an `edit` and to
check what a person typed) and the tools of a `create_agent` graph by name (where to find that tool).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from itertools import chain
from typing import Any

from jsonschema import Draft202012Validator
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

from ext_r2c.core import InvalidArguments, Problem, ToolSpec

__all__ = ["schema_of", "tool_from_langchain", "tools_by_name", "tools_from_langchain"]


def schema_of(tool: Any) -> dict[str, Any]:
    """A copy of the schema of the arguments the model sees, as JSON Schema, with no `title` and no
    top-level `description`.

    LangChain puts the tool's own description at the top of what it shows the model, whether the
    `args_schema` is a plain dict or a pydantic class (it builds the model with the tool's description as
    its docstring). The `ToolSpec` carries the description itself, so it is dropped here.
    """
    found = tool.tool_call_schema
    # Deep: the model class LangChain makes for a tool answers `model_json_schema()` with one shared
    # dict, and a dict `args_schema` is the tool's own object, so a shallow copy would still alias it.
    if isinstance(found, type) and issubclass(found, BaseModel):
        schema = deepcopy(found.model_json_schema())
    else:
        schema = deepcopy(dict(found))
    schema.pop("title", None)
    schema.pop("description", None)
    return schema


def tools_by_name(graph: Any) -> Mapping[str, Any] | None:
    """The tools of a `create_agent` graph, by name; `None` when the graph does not keep them where
    the bridge can find them (a node whose `bound` has `tools_by_name`)."""
    for node in graph.nodes.values():
        found = getattr(getattr(node, "bound", None), "tools_by_name", None)
        if isinstance(found, Mapping) and found:
            return dict(found)
    return None


# --- A LangChain tool as a ToolSpec (FR-024, FR-025) -------------------------------------------------------


def _injected(tool: BaseTool) -> list[str]:
    """The arguments a running graph fills in (`InjectedState`, `InjectedStore`, `ToolRuntime`,
    `InjectedToolCallId`, `InjectedToolArg`): in the tool's input model, not in what the model sees.
    Two readings, because neither sees everything. The fields of the input model against the fields shown
    to the model: `tool.args` is not used, for a legacy `Tool` with no `args_schema` reports one made-up
    argument that is not in its input model. And the tool's own list of the keys it fills in from the call
    (`_injected_args_keys`, read from its signature): with an explicit `args_schema` the input model *is* that
    schema, so a parameter it does not list is in neither model above, and LangChain would still copy a key of
    that name from the call into the tool (R19 S2). A plain JSON Schema has no model, and only the second
    reading applies."""
    names: list[str] = []
    if not isinstance(tool.args_schema, dict):
        shown = tool.tool_call_schema.model_fields
        names = [name for name in tool.get_input_schema().model_fields if name not in shown]
    return names + sorted(set(getattr(tool, "_injected_args_keys", ())) - set(names))


def _keyed(check: Draft202012Validator, args: dict[str, Any]) -> Iterator[tuple[str | None, str]]:
    """What breaks the schema, each with the argument it is about (`None`: the arguments as a whole)."""
    for err in check.iter_errors(args):
        path = list(err.absolute_path)
        if path:
            yield str(path[0]), err.message
        elif err.validator == "required" and isinstance(err.instance, dict):
            for name in err.validator_value:
                if name not in err.instance:
                    yield name, "This value is required."
        else:
            yield None, err.message


def _problems(found: Iterable[tuple[str | None, str]], order: Sequence[str]) -> list[Problem]:
    """One problem per argument (the first message), the whole first, then in the schema's order."""
    first: dict[str | None, str] = {}
    for key, message in found:
        first.setdefault(key, message)
    rank = {key: i for i, key in enumerate(order)}
    keys = sorted(first, key=lambda key: -1 if key is None else rank.get(key, len(rank)))
    return [Problem("invalid_args", key, first[key]) for key in keys]


def tool_from_langchain(tool: BaseTool) -> ToolSpec:
    """A `ToolSpec` from a LangChain tool: its name, its description and the schema of the arguments the
    model fills in (a copy, no `title`; a tool with a plain JSON Schema as `args_schema` too).

    `call` checks the arguments before the tool runs, the way `tool_from_function` does, and raises
    `InvalidArguments` if they break the schema or what the tool's own pydantic `args_schema` says (the
    model-visible schema leaves out `extra="forbid"` and validators). A sync tool runs off the event loop.

    A tool that needs something only a running graph supplies (an injected argument) is refused here,
    with a `TypeError` that names the tool and the argument, not at its first call.
    """
    if not isinstance(tool, BaseTool):
        raise TypeError(f"tool_from_langchain needs a LangChain tool (a BaseTool), not {type(tool).__name__}.")
    injected = _injected(tool)
    if injected:
        raise TypeError(
            f"The tool {tool.name!r} takes {', '.join(repr(name) for name in injected)} from the graph that runs "
            "it, so it cannot be served on its own."
        )
    schema = schema_of(tool)
    order = list(schema.get("properties", {}))
    if tool.args_schema is None and set(tool.args) != set(order):
        # A legacy `Tool`: it says its argument is `tool_input`, but its schema is made from `_run(*args, ...)`.
        raise TypeError(
            f"The tool {tool.name!r} has no `args_schema`, so there is no schema of its arguments to pass on: "
            "give it one."
        )
    check = Draft202012Validator(schema)
    model = tool.args_schema if isinstance(tool.args_schema, type) and issubclass(tool.args_schema, BaseModel) else None
    # Without a word of its own on other keys the schema shown would let anything through (that is JSON Schema's
    # default, and the model LangChain shows leaves out `extra="forbid"`). A function tool of the core forbids
    # them, and so does this: only what the schema offered reaches the tool (R19 S1, S2).
    closed = "additionalProperties" not in schema and "patternProperties" not in schema

    async def call(args: Mapping[str, Any]) -> Any:
        given = dict(args)
        undeclared = ((key, "This argument is not accepted.") for key in given if closed and key not in order)
        problems = _problems(chain(_keyed(check, given), undeclared), order)
        if not problems and model is not None:
            try:
                model.model_validate(given)
            except ValidationError as exc:  # what the schema shown could not say
                problems = _problems(
                    ((str(e["loc"][0]) if e["loc"] else None, "This value is not accepted.") for e in exc.errors()),
                    order,
                )
        if problems:
            raise InvalidArguments(problems)
        # `arun`, not `ainvoke`: `ainvoke` reads a dict with `type == "tool_call"` as an envelope and runs its own
        # `args` in place of the keys beside it, so what was checked would not be what runs (R19 S1).
        return await tool.arun(given)

    return ToolSpec(tool.name, tool.description, schema, call)


def tools_from_langchain(tools: Iterable[BaseTool]) -> list[ToolSpec]:
    """`tool_from_langchain` for each tool, in order. One refusal refuses the whole list: nothing comes back."""
    return [tool_from_langchain(tool) for tool in tools]
