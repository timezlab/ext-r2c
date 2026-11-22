"""`input_required`: a turn that ends asking the caller (spec 006, research R12; FR-022; D10).

A graph built with a `response_format` ends a turn with a structured reply in its `structured_response`.
When that reply says `status == "input_required"` and has a `message`, the turn did not finish what the
caller asked: the message is a question for the caller. The caller's answer is the next human message
of the same thread, so there is no interrupt and no resume: the question is read from the thread's saved
state, and only from there (a restart gives the same question).

Pure: a structured reply in, a question out. No graph, no queue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from ext_r2c.core import AnswerBy, Field, Question

from ._pauses import title_and_description

__all__ = ["asked_at_end", "pending_question", "wanted"]

_INPUT_REQUIRED = "input_required"


def _plain(reply: Any) -> Mapping[str, Any] | None:
    """The structured reply as a mapping: a pydantic model by `model_dump`, a dataclass by `asdict`, a
    mapping as it is. Anything else is not read."""
    if isinstance(reply, BaseModel):
        return reply.model_dump()
    if is_dataclass(reply) and not isinstance(reply, type):
        return asdict(reply)
    return reply if isinstance(reply, Mapping) else None


def wanted(reply: Any) -> str | None:
    """The message of a structured reply that asks the caller for input, or `None`.

    Only the pair `status` and `message` is read: an `Enum` status counts by its value, and a message
    with no words is not a question."""
    fields = _plain(reply)
    if fields is None:
        return None
    status = fields.get("status")
    if isinstance(status, Enum):
        status = status.value
    message = fields.get("message")
    if status != _INPUT_REQUIRED or not isinstance(message, str) or not message.strip():
        return None
    return message


def _last_ai(messages: Sequence[Any]) -> int | None:
    return next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], AIMessage)), None)


def asked_at_end(messages: Sequence[Any], reply: Any) -> Question | None:
    """The question a turn that ended with `reply` asks: the message as the title (its first line, cut),
    the whole message in the description when the title is not all of it, named after the turn's last AI
    message so the same turn always gives the same id, before and after a restart."""
    message = wanted(reply)
    if message is None:
        return None
    last = _last_ai(messages)
    title, description = title_and_description(message)
    return Question(
        id=f"lg-ir-{messages[last].id if last is not None else None}",
        title=title,
        description=description,
        answer_by=AnswerBy(role="caller"),
        fields=[Field(key="answer", header="Answer", text="Your answer, sent to the agent as the next message", type="text")],
    )


def pending_question(state: Any) -> Question | None:
    """The question the thread is waiting on, read from its saved state: no interrupt is pending, no human
    message follows the last AI message, and the structured reply the state holds still asks."""
    if state.interrupts:
        return None
    values = state.values if isinstance(state.values, dict) else {}
    found = values.get("messages")
    messages = list(found) if isinstance(found, (list, tuple)) else []
    last = _last_ai(messages)
    if last is None or any(isinstance(m, HumanMessage) for m in messages[last + 1 :]):
        return None
    return asked_at_end(messages, values.get("structured_response"))
