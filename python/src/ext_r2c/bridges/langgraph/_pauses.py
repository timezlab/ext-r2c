"""Reading a pause from the checkpointer (spec 006, research R8; FR-014 to FR-016, FR-018).

A pause is what the checkpointer holds, never what the stream said: only a pending interrupt the
checkpointer lists can be resumed, so only that is offered. Each pending interrupt is classified by
the shape of its value, in this order: a `per_call` middleware approval, a `batched` one, and a
hand-written R2C `question` or `approval` (what a graph that speaks R2C writes), which is asked as it
is, under its own id. Any other shape comes with the fallback question.

A call the middleware gates is one `Pause` (`per_call`) or one per call of the batch (`batched`), each
a request the caller answers on its own, in the order the model made the calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage

from ext_r2c.core import (
    Answer,
    AnswerBy,
    Approval,
    ApproverBy,
    Field,
    InvalidObject,
    Question,
    Subject,
    parse,
)

from ._decisions import offered, schema_decisions
from .tools import schema_of

__all__ = ["Pause", "read_pauses", "resume_value"]

_PER_CALL_KEYS = ("tool_call_id", "name", "args", "description")


@dataclass(frozen=True, slots=True)
class Pause:
    """One pending request, as the caller is asked about it.

    `kind` says how the payload was read; the other fields describe a gated tool call (they are empty
    for a request the graph wrote itself): the call's tool, its place in a batch, the decisions the
    graph accepts for it, and whether it takes only a reply.
    """

    request: Question | Approval
    interrupt_id: str
    kind: Literal["tool_call", "batch_call", "own_request"] = "own_request"
    tool_name: str | None = None
    tool_call_id: str | None = None
    position: int | None = None
    batch_size: int | None = None
    allowed: frozenset[str] = frozenset()
    respond_only: bool = False


def _own_request(value: Any) -> Question | Approval | None:
    """The interrupt's value as an R2C request, when it is a valid one the caller may answer."""
    if not isinstance(value, Mapping):
        return None
    try:
        parsed = parse(value)
    except InvalidObject:
        return None
    return parsed if isinstance(parsed, (Question, Approval)) else None


def _is_per_call(value: Any) -> bool:
    return isinstance(value, Mapping) and all(k in value for k in _PER_CALL_KEYS) and isinstance(value["name"], str)


def _is_batched(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("action_requests"), list)
        and isinstance(value.get("review_configs"), list)
    )


def _tool_pause(
    *,
    request_id: str,
    interrupt_id: str,
    kind: Literal["tool_call", "batch_call"],
    name: str,
    args: Any,
    description: Any,
    allowed: frozenset[str],
    tools: Mapping[str, Any] | None,
    tool_call_id: str | None = None,
    position: int | None = None,
    batch_size: int | None = None,
) -> Pause:
    """The request for one gated call: an approval, or a question when the call takes only a reply."""
    shown = str(description) if isinstance(description, str) and description else None
    common: dict[str, Any] = {
        "interrupt_id": interrupt_id, "kind": kind, "tool_name": name, "tool_call_id": tool_call_id,
        "position": position, "batch_size": batch_size, "allowed": allowed,
    }
    if allowed == {"respond"}:
        question = Question(
            id=request_id,
            title=f"Reply for {name}",
            description=shown,
            answer_by=AnswerBy(role="person"),
            fields=[Field(key="reply", header="Reply", text="Your reply, given to the agent as the result of this call", type="text")],
        )
        return Pause(question, respond_only=True, **common)
    schema = schema_of(tools[name]) if tools and name in tools else None
    decisions = offered(allowed, schema is not None)
    if not decisions:
        raise ValueError(
            f"Nothing the graph allows for the call to {name} can be offered to a person "
            "(an edit needs the tool's arguments schema, and the graph does not show it)."
        )
    approval = Approval(
        id=request_id,
        title=f"Approve {name}?",
        description=shown,
        answer_by=ApproverBy(role="person"),
        subject=Subject(
            type="tool_call",
            name=name,
            args=dict(args) if isinstance(args, Mapping) else None,
            args_schema=schema if "edit" in decisions else None,
        ),
        decisions=decisions,  # type: ignore[arg-type]
    )
    return Pause(approval, **common)


def _per_call(interrupt: Any, tools: Mapping[str, Any] | None) -> Pause:
    value = interrupt.value
    name = value["name"]
    allowed = schema_decisions(getattr(interrupt, "response_schema", None))
    if not allowed:
        raise ValueError(f"The decisions the graph allows for the call to {name} could not be read, so it is not asked.")
    return _tool_pause(
        request_id=f"lg-{interrupt.id}", interrupt_id=interrupt.id, kind="tool_call", name=name,
        args=value["args"], description=value["description"], allowed=allowed, tools=tools,
        tool_call_id=value["tool_call_id"] if isinstance(value["tool_call_id"], str) else None,
    )


def _batched(interrupt: Any, tools: Mapping[str, Any] | None) -> list[Pause]:
    requests, configs = interrupt.value["action_requests"], interrupt.value["review_configs"]
    unreadable = ValueError("The decisions the graph allows for a batch of calls could not be read, so it is not asked.")
    if len(requests) != len(configs):
        raise unreadable
    pauses: list[Pause] = []
    for position, (request, config) in enumerate(zip(requests, configs, strict=True)):
        if not (isinstance(request, Mapping) and isinstance(request.get("name"), str) and isinstance(config, Mapping)):
            raise unreadable
        allowed = config.get("allowed_decisions")
        if not isinstance(allowed, list) or not allowed:
            raise unreadable
        pauses.append(_tool_pause(
            request_id=f"lg-{interrupt.id}-{position}", interrupt_id=interrupt.id, kind="batch_call",
            name=request["name"], args=request.get("args"), description=request.get("description"),
            allowed=frozenset(str(d) for d in allowed), tools=tools, position=position, batch_size=len(requests),
        ))
    return pauses


def _call_order(values: Any) -> dict[str, int]:
    """The place of each tool call in the last AI message: the order the model made them in."""
    messages = values.get("messages") if isinstance(values, dict) else None
    for message in reversed(messages if isinstance(messages, (list, tuple)) else ()):
        if isinstance(message, AIMessage):
            return {call["id"]: n for n, call in enumerate(message.tool_calls) if call.get("id")}
    return {}


def read_pauses(state: Any, tools: Mapping[str, Any] | None = None) -> list[Pause]:
    """The pending requests of a thread, in the order they are asked: tool approvals first, in the
    model's order, then the requests the graph wrote itself, in the order LangGraph lists them.

    `state` is the thread's `StateSnapshot`; `tools` the graph's tools by name (to find the schema of
    an `edit`). Raises `ValueError`, with a reason a person can read, for a gated call whose decisions
    cannot be read or offered: the run then ends `failed` before anything is asked.
    """
    approvals: list[Pause] = []
    others: list[Pause] = []
    for interrupt in state.interrupts:
        if _is_per_call(interrupt.value):
            approvals.append(_per_call(interrupt, tools))
        elif _is_batched(interrupt.value):
            approvals.extend(_batched(interrupt, tools))
        else:
            request = _own_request(interrupt.value)
            if request is None:
                raise RuntimeError("this kind of pause is not supported yet")
            others.append(Pause(request, interrupt.id))
    order = _call_order(state.values)
    approvals.sort(key=lambda p: (order.get(p.tool_call_id or "", len(order)), p.position or 0))
    return approvals + others


def resume_value(answer: Answer) -> dict[str, Any] | None:
    """What `interrupt()` returns inside the graph for a request it wrote itself: the answer's value,
    or `None` when declined."""
    return None if answer.outcome == "declined" else dict(answer.value or {})
