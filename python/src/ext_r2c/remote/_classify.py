"""What each argument of ``Remote`` is, decided by its shape (spec 007, research R4 to R6).

Nothing here loads a door. A check that needs a door's class (``SourceTool``) is given the class, so
this module imports the core only and a ``Remote`` that exposes one door never touches the other's.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from ..core import ToolSpec, tool_from_function

__all__ = ["DOORS", "AgentKind", "agent_kind", "normalise_approve", "normalise_tools", "read_expose"]

DOORS = ("a2a", "mcp")
"""The doors, in the order they start."""

AgentKind = Literal["source", "executor"]

_TOOL_KINDS = (
    "tools: each entry is a ToolSpec, a SourceTool, or a plain function or method; "
    "a LangChain tool is converted in your module with tools_from_langchain(...), from ext_r2c.bridges.langgraph"
)


def read_expose(expose: Any) -> tuple[tuple[str, ...], list[str]]:
    """The doors ``expose`` names that exist, in starting order, and what is wrong with the rest.

    A value that is not a list of names is a ``TypeError`` at once: a bare ``"mcp"`` would otherwise
    be read letter by letter. An empty list, an unknown door and a door named twice are problems
    for the one ``RemoteError``; the doors that do exist are still loaded and checked.
    """
    if not isinstance(expose, (list, tuple, set, frozenset)):
        raise TypeError(f'expose: is a list of door names, such as ["a2a", "mcp"], not {type(expose).__name__}')
    names = list(expose)
    for name in names:
        if not isinstance(name, str):
            raise TypeError(f'expose: each entry is "a2a" or "mcp", not {type(name).__name__}')
    problems: list[str] = []
    if not names:
        problems.append('expose: names no door; give "a2a", "mcp" or both')
    if any(name not in DOORS for name in names):
        problems.append('expose: names a door that does not exist; the doors are "a2a" and "mcp"')
    for door in DOORS:
        if names.count(door) > 1:
            problems.append(f'expose: names "{door}" more than once; name each door once')
    return tuple(door for door in DOORS if door in names), problems


def agent_kind(agent: Any) -> AgentKind:
    """``"source"`` for an ``AgentSource``, ``"executor"`` for an a2a-sdk ``AgentExecutor``.

    By shape, source first: ``AgentSource`` is a protocol that ``isinstance`` cannot check, and the
    executor's class lives in an SDK that may not be installed when only MCP is exposed.
    """
    if (hasattr(agent, "card") and hasattr(agent, "pause")
            and callable(getattr(agent, "run", None)) and callable(getattr(agent, "resume", None))):
        return "source"
    if callable(getattr(agent, "execute", None)) and callable(getattr(agent, "cancel", None)):
        return "executor"
    raise TypeError(
        "agent: is an AgentSource (an object with card, pause, run and resume, such as a LangGraphAgent) "
        f"or an a2a-sdk AgentExecutor (an object with execute and cancel), not {type(agent).__name__}"
    )


def _entries(argument: str, value: Any, what: str) -> Sequence[Any]:
    """``value`` as a sequence; a string is one value, not a list of them."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{argument}: is a list of {what}, not {type(value).__name__}")
    return value


def normalise_tools(tools: Any, source_tool: type) -> tuple[Any, ...]:
    """Each entry of ``tools`` as what the MCP door serves: a ``ToolSpec`` or a ``SourceTool`` kept, a
    function or a method converted by the core (whose own refusals pass through unchanged).

    Anything else is refused with one fixed text. ``Remote`` recognises no framework's tool object:
    the owner converts it in their own module, so no bridge is imported here.
    """
    served = []
    for tool in _entries("tools", tools, "tools"):
        if isinstance(tool, (ToolSpec, source_tool)):
            served.append(tool)
        elif inspect.isroutine(tool):
            served.append(tool_from_function(tool))
        else:
            raise TypeError(_TOOL_KINDS)
    return tuple(served)


def normalise_approve(approve: Any) -> dict[str, Any]:
    """``approve`` as the mapping the MCP door takes: a list of tool names means ``{name: True}``."""
    if isinstance(approve, Mapping):
        named = dict(approve)
    else:
        named = dict.fromkeys(_entries("approve", approve, "tool names, or a mapping of tool name to Approve or bool"),
                              True)
    for name in named:
        if not isinstance(name, str):
            raise TypeError(f"approve: a tool is named by a str, not {type(name).__name__}")
    return named
