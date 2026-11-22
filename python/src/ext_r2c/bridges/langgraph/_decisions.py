"""The decisions of a tool call, in both directions (spec 006, research R9; FR-016 to FR-020).

The graph's words are `approve`, `edit`, `reject` and `respond`; R2C's are `allow`, `edit` and `deny`.
This module reads which of the graph's decisions a call accepts, says which R2C decisions to offer for
them, turns an answer back into the graph's decision, and refuses, before the graph is touched, any
answer the graph would refuse: a `batched` resume the graph refuses leaves the thread unable to go on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ext_r2c.core import Answer

if TYPE_CHECKING:
    from ._pauses import Pause

__all__ = ["check", "offered", "schema_decisions", "to_graph"]

_GRAPH_DECISIONS = ("approve", "edit", "reject", "respond")


def schema_decisions(schema: Any) -> frozenset[str]:
    """The decisions a `per_call` interrupt's `response_schema` accepts: every `properties.type.const`
    in it, `$defs` and `oneOf` included. Nothing readable gives an empty set."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            kind = properties.get("type") if isinstance(properties, dict) else None
            const = kind.get("const") if isinstance(kind, dict) else None
            if const in _GRAPH_DECISIONS:
                found.add(const)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return frozenset(found)


def offered(allowed: frozenset[str], has_schema: bool) -> list[str]:
    """The R2C decisions to offer, in the standard's order. `edit` only where there is a schema to
    check what a person typed; `respond` is not a decision of R2C (a call that allows only it is a
    question)."""
    out: list[str] = []
    if "approve" in allowed:
        out.append("allow")
    if "edit" in allowed and has_schema:
        out.append("edit")
    if "reject" in allowed:
        out.append("deny")
    return out


def to_graph(answer: Answer, pause: Pause) -> dict[str, Any]:
    """The graph's decision for an answer that the core's check accepted.

    An edit always names the call's own tool: an R2C answer has no tool name to take, so an edit can
    never switch tools.
    """
    if answer.outcome == "declined":  # R2C-ANSWER-3: a declined approval is a deny
        return {"type": "reject", **({"message": answer.note} if answer.note else {})}
    value = answer.value or {}
    if pause.respond_only:
        return {"type": "respond", "message": value["reply"]}
    chosen = value["decision"]
    if chosen == "allow":
        return {"type": "approve"}
    if chosen == "deny":
        return {"type": "reject", **({"message": value["reason"]} if value.get("reason") else {})}
    return {"type": "edit", "edited_action": {"name": pause.tool_name, "args": value["args"]}}


def check(answer: Answer, pause: Pause) -> None:
    """Refuse with a readable `ValueError` an answer whose decision the call does not accept.

    The core's check has already run against the request the bridge asked; what it cannot see is the
    graph's side: a declined answer is a `reject`, and the call may not allow one.
    """
    if pause.tool_name is None:  # a request the graph wrote itself: its own business
        return
    kind = to_graph(answer, pause)["type"]
    if kind in pause.allowed:
        return
    if kind == "reject":
        raise ValueError(f"The call to {pause.tool_name} cannot be rejected: the agent does not allow it.")
    raise ValueError(f"The call to {pause.tool_name} does not allow this decision ({kind}).")
