"""The graph's own tools, read for what an approval needs (spec 006, research R16).

Phase 5 needs two private helpers: the arguments schema of a tool (to offer an `edit` and to check
what a person typed) and the tools of a `create_agent` graph by name (where to find that tool). The
public conversion of a LangChain tool into a `ToolSpec` comes later in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

__all__ = ["schema_of", "tools_by_name"]


def schema_of(tool: Any) -> dict[str, Any]:
    """A copy of the schema of the arguments the model sees, as JSON Schema, with no `title`.

    A tool whose `args_schema` is a plain dict comes back from LangChain with the tool's own
    description added at the top; the `ToolSpec` carries the description itself, so it is dropped here.
    """
    found = tool.tool_call_schema
    # Deep: the model class LangChain makes for a tool answers `model_json_schema()` with one shared
    # dict, and a dict `args_schema` is the tool's own object, so a shallow copy would still alias it.
    if isinstance(found, type) and issubclass(found, BaseModel):
        schema = deepcopy(found.model_json_schema())
    else:
        schema = deepcopy(dict(found))
        schema.pop("description", None)
    schema.pop("title", None)
    return schema


def tools_by_name(graph: Any) -> Mapping[str, Any] | None:
    """The tools of a `create_agent` graph, by name; `None` when the graph does not keep them where
    the bridge can find them (a node whose `bound` has `tools_by_name`)."""
    for node in graph.nodes.values():
        found = getattr(getattr(node, "bound", None), "tools_by_name", None)
        if isinstance(found, Mapping) and found:
            return dict(found)
    return None
